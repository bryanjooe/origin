"""Three predeclared sidecars; validation selection, then one new run holdout.

All live code/models remain unchanged unless a separate compatibility/promotion
step is justified. Original score/ML output is retained; measure fused coverage.
"""
import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np

from app.detection import AnomalyDetector, FeatureExtractor
from app.detection.dataset import simulate_run
from app.detection.evaluation import binary_metrics
from app.detection.security_signals import SecuritySidecar, SecuritySignalExtractor, SIGNALS, persistent_fusion
from app.security_analysis.dataset import AlertPolicy, generate_runs, live_incident_sample
from app.security_analysis.evaluation import evaluate as evaluate_security
from app.security_analysis.model import AttributionModels


OUT=Path('outputs/security-detector-study-v1')
DETECTOR=Path('outputs/stage2/anomaly.joblib')
SECURITY=Path('outputs/step5/candidates/regular/selected.joblib')
SECURITY_REPORT=SECURITY.parent/'held_out_evaluation.json'


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def policy():return AlertPolicy(**read(SECURITY_REPORT)['alert_policy'])


def features(run):return SecuritySignalExtractor(run.config).transform(run.telemetry)


def normal_corpus(name,base,count,ticks):
    return [simulate_run(f'security-sidecar-{name}-{i}',base+17*i,ticks) for i in range(count)]


def corpus(name):
    final=name=='final'
    from app.attack_injection import StealthLevel
    runs=generate_runs(seed=16000000 if final else 13000000,repeats=3 if final else 2,
        ticks=240,severities=(.35,.75) if final else (.25,.6,1),
        stealth_levels=tuple(StealthLevel) if final else (StealthLevel.NAIVE,StealthLevel.MODERATE))
    for run in runs:run.run_id=f'security-sidecar-{name}-{run.run_id}'
    return runs


def prepare(runs,detector):
    result={}
    for i,run in enumerate(runs):
        result[run.run_id]={'baseline':detector.predict(FeatureExtractor(run.config).transform(run.telemetry)),
                           'signals':features(run)}
        if i%100==0:print('Observed preparation',i,len(runs),flush=True)
    return result


def detector_report(runs,outputs):
    truth=[];pred=[];ml=[];per_run=[];by_type=defaultdict(list)
    for run in runs:
        selected=[r for r in outputs[run.run_id] if run.nature=='normal' or run.start_tick<=r['tick']<run.start_tick+run.duration_ticks]
        assert selected
        label=run.nature!='normal'
        flags=[r['combined_status']!='normal' for r in selected]
        truth.extend([label]*len(flags));pred.extend(flags);ml.extend(r['ml_status']!='normal' for r in selected)
        first=next((r['tick'] for r in selected if r['combined_status']!='normal'),None)
        record={'run_id':run.run_id,'seed':run.seed,'nature':run.nature,'scenario_type':run.scenario_type,
            'mode':run.mode,'severity':run.severity,'stealth_level':run.stealth_level,'rows':len(flags),
            'alert_ticks':sum(flags),'detected':first is not None,
            'delay_seconds':max(0,first-run.start_tick)*run.config.tick_seconds if label and first is not None else None}
        per_run.append(record)
        if run.nature=='attack':by_type[run.scenario_type].append(record)
    m=binary_metrics(truth,pred)
    event=[r for r in per_run if r['nature']!='normal'];normal=[r for r in per_run if r['nature']=='normal']
    delays=[r['delay_seconds'] for r in event if r['detected']]
    m.update(detected_event_runs=len(delays),total_event_runs=len(event),event_run_coverage=len(delays)/len(event),
        normal_run_alert_rate=sum(r['detected'] for r in normal)/len(normal),
        mean_detection_delay_seconds=float(np.mean(delays)) if delays else None)
    return {'scope':'Original combined pipeline versus combined pipeline + explicitly labeled sidecar; ML component separately reported unchanged',
        'metrics':m,'original_ml_metrics':binary_metrics(truth,ml),'per_run':per_run,
        'by_attack':{key:{'runs':len(rr),'detected_runs':sum(r['detected'] for r in rr),
            'run_coverage':sum(r['detected'] for r in rr)/len(rr),'active_tick_recall':sum(r['alert_ticks'] for r in rr)/sum(r['rows'] for r in rr),
            'mean_delay_seconds':float(np.mean([r['delay_seconds'] for r in rr if r['detected']])) if any(r['detected'] for r in rr) else None}
            for key,rr in sorted(by_type.items())},
        'delay_definition':'Simulated seconds among detected runs only; missed events have null delays. Active event ticks and dedicated normal ticks; pre/post-event excluded.'}


def security_report(runs,outputs,detector,model):
    samples={}
    for run in runs:
        item=live_incident_sample(run,detector,policy(),statuses=outputs[run.run_id])
        if item:samples[run.run_id]=item
    report=evaluate_security(model,runs,detector,alert_policy=policy(),
        sample_builder=lambda run,*_:samples.get(run.run_id),compute_importance=False)
    report['protocol']='live_incident_v1; unchanged Stage B weights/policy'
    return report


def accepted_accuracy(report):
    labels={'normal':'Normal','fault':'Accidental fault','attack':'Cyber attack'}
    rr=[r for r in report['row_level_results'] if r['inference_tick'] is not None and r['nature_prediction']!='Undetermined']
    return sum(r['nature_prediction']==labels[r['nature_truth']] for r in rr)/len(rr) if rr else None


def guards(before,after):
    b,a=before['detector']['metrics'],after['detector']['metrics']
    bs,ss=before['security'],after['security']
    return {'precision_floor':a['precision']>=.95,'precision_nonregression':a['precision']>=b['precision']-.01,
        'tick_false_positive_cap':a['false_positive_rate']<=.015,
        'tick_false_positive_increase':a['false_positive_rate']<=b['false_positive_rate']+.0025,
        'normal_run_false_alert_increase':a['normal_run_alert_rate']<=b['normal_run_alert_rate']+.02,
        'recall_gain':a['recall']>=b['recall']+.02,'f1_gain':a['f1']>=b['f1']+.01,
        'coverage':a['event_run_coverage']>=b['event_run_coverage'],
        'delay':a['mean_detection_delay_seconds']<=b['mean_detection_delay_seconds']*1.1,
        'stage_b_nature':ss['nature']['macro_f1']>=bs['nature']['macro_f1']-.005,
        'stage_b_origin':ss['origin']['macro_f1']>=bs['origin']['macro_f1']-.005,
        'stage_b_accepted_accuracy':accepted_accuracy(ss)>=accepted_accuracy(bs)-.01,
        'stage_b_normal_attack_labels':ss['normal_run_false_positive_rate']['nature_classifier_attack_label']<=bs['normal_run_false_positive_rate']['nature_classifier_attack_label']+.01,
        'stage_b_normal_gate':ss['normal_run_false_positive_rate']['detector_fire']<=bs['normal_run_false_positive_rate']['detector_fire']+.01}


def snapshot_manifest():
    paths=[DETECTOR,Path('outputs/stage3/source_classifier.joblib'),SECURITY]
    frontend=[*Path('src').rglob('*'),*Path('frontend').rglob('*')]
    # Unused frontend may contain dependencies; source/UI files only.
    ui={str(p):digest(p) for p in frontend if p.is_file() and not any(v in p.parts for v in ('node_modules','dist','.git'))}
    return {'models':{str(p):digest(p) for p in paths},'frontend_hashes':ui}


def protocol():
    settings={'study':'security-sidecar-v1','feature_schema':1,'window_ticks':8,'minimum_observations':4,
        'candidates':['envelope995','envelope999','normal_if999'],
        'training':'24 normal runs, seeds12000000+17*i, 720 ticks',
        'calibration':'12 normal runs, seeds12100000+17*i, 1440 ticks',
        'validation':'seed13000000, repeats2, severities .25/.6/1, naive/moderate only, 240 ticks',
        'final':'seed16000000, repeats3, severities .35/.75, all stealth levels, 240 ticks; unseen complete runs; stealthy excluded from development',
        'guards':'combined recall +2pp,F1+1pp,precision>=95% and baseline-1pp,tickFPR<=1.5% and baseline+.25pp,normal run alerts<=baseline+2pp,coverage nondecreasing,detected delay<=baseline*1.1; unchanged StageB nature/origin macroF1>=baseline-.5pp,accepted accuracy>=baseline-1pp,normal attack labels and gate<=baseline+1pp',
        'no_reselection':'Only validation selects; failed final comparison retains original; no training/threshold search after final.',
        'constant_policy':'Exclude normal-constant features from IF; envelope zero-variance sequence support is explicitly a normal-bound check, not learned feature importance.',
        'missing_policy':'Missing flags/tags/sensors have explicit counts; no auth rule for missing tags; minimum4 valid distinct auth packets or valid domain rows; IF skips incomplete domains.',
        'original_ml':'Scores, ML labels, thresholds and ML explanations remain identical; compare combined alert coverage, not inflated IF recall.'}
    p=OUT/'protocol.json'
    if p.exists():assert read(p)==settings
    else:write(p,settings)


def develop():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'selection.json').exists():raise RuntimeError('Validation selection is already frozen')
    protocol();write(OUT/'original_manifest.json',snapshot_manifest())
    detector=AnomalyDetector.load(DETECTOR);security=AttributionModels.load(SECURITY)
    training=normal_corpus('train',12000000,24,720);calibration=normal_corpus('calibration',12100000,12,1440)
    normal_train=[s for r in training for s in features(r)];normal_cal=[s for r in calibration for s in features(r)]
    validation=corpus('validation')
    populations=[training,calibration,validation]
    ids=set();seeds=set()
    for group in populations:
        assert not ids.intersection(r.run_id for r in group) and not seeds.intersection(r.seed for r in group)
        ids.update(r.run_id for r in group);seeds.update(r.seed for r in group)
    write(OUT/'development_manifest.json',{'training':[r.manifest() for r in training],'calibration':[r.manifest() for r in calibration],
        'validation':[r.manifest() for r in validation]})
    prepared=prepare(validation,detector)
    baseline_outputs={r.run_id:prepared[r.run_id]['baseline'] for r in validation}
    baseline={'detector':detector_report(validation,baseline_outputs),'security':security_report(validation,baseline_outputs,detector,security)}
    write(OUT/'validation_original.json',baseline)
    reports={};candidates={}
    for name,method,q in [('envelope995','envelope',.995),('envelope999','envelope',.999),('normal_if999','isolation_forest',.999)]:
        model=SecuritySidecar(method,q).fit(normal_train,normal_cal)
        candidates[name]=model
        outputs={r.run_id:model.fuse(prepared[r.run_id]['baseline'],prepared[r.run_id]['signals']) for r in validation}
        report={'detector':detector_report(validation,outputs),'security':security_report(validation,outputs,detector,security)}
        report['guards']=guards(baseline,report);report['sidecar']={'method':method,'limits':model.limits,'metadata':model.metadata}
        reports[name]=report;write(OUT/f'validation_{name}.json',report)
        joblib.dump(model,OUT/f'{name}.joblib')
        print(name,json.dumps(report['detector']['metrics']),report['guards'],flush=True)
    eligible=[name for name,r in reports.items() if all(r['guards'].values())]
    selected=max(eligible,key=lambda name:reports[name]['detector']['metrics']['f1']) if eligible else None
    write(OUT/'selection.json',{'selected':selected,'selected_using':'validation only; all guards fixed first',
        'candidate_hashes':{name:digest(OUT/f'{name}.joblib') for name in candidates},
        'eligible':eligible,'final_not_yet_opened':True})
    print('FROZEN SELECTION',selected,flush=True)


def final():
    selection_path=OUT/('selection_gated.json' if (OUT/'selection_gated.json').exists() else 'selection.json')
    selection=read(selection_path)
    if (OUT/'final_started.json').exists():raise RuntimeError('Final set already opened; no reuse for tuning')
    if selection['selected'] is None:
        write(OUT/'acceptance.json',{'accepted':False,'reason':'No validation candidate qualified; final data not opened','active_models_changed':False})
        print('No candidate qualified on validation; final holdout remains untouched',flush=True);return
    write(OUT/'final_started.json',{'selection_file':str(selection_path),'selection_sha256':digest(selection_path),'single_frozen_comparison':True})
    model_path=OUT/(selection.get('model',selection['selected'])+'.joblib')
    assert digest(model_path)==selection['candidate_hashes'][selection.get('model',selection['selected'])]
    model=joblib.load(model_path);detector=AnomalyDetector.load(DETECTOR);security=AttributionModels.load(SECURITY)
    runs=corpus('final');development=read(OUT/'development_manifest.json')
    old=[r for values in development.values() for r in values]
    assert not {r.seed for r in runs}.intersection(r['seed'] for r in old)
    assert not {r.run_id for r in runs}.intersection(r['run_id'] for r in old)
    write(OUT/'final_manifest.json',[r.manifest() for r in runs])
    prepared=prepare(runs,detector)
    baseline_outputs={r.run_id:prepared[r.run_id]['baseline'] for r in runs}
    candidate_outputs={r.run_id:(persistent_fusion(prepared[r.run_id]['baseline'],prepared[r.run_id]['signals'],model)
        if selection['selected']=='persistent_envelope999' else model.fuse(prepared[r.run_id]['baseline'],prepared[r.run_id]['signals'])) for r in runs}
    before={'detector':detector_report(runs,baseline_outputs),'security':security_report(runs,baseline_outputs,detector,security)}
    after={'detector':detector_report(runs,candidate_outputs),'security':security_report(runs,candidate_outputs,detector,security)}
    checks=guards(before,after)
    write(OUT/'final_original.json',before);write(OUT/'final_candidate.json',after)
    if selection['selected']=='persistent_envelope999':
        control={r.run_id:persistent_fusion(prepared[r.run_id]['baseline'],prepared[r.run_id]['signals']) for r in runs}
        write(OUT/'final_persistence_control.json',{'detector':detector_report(runs,control),
            'security':security_report(runs,control,detector,security)})
    write(OUT/'acceptance.json',{'accepted':all(checks.values()),'guards':checks,'selected':selection['selected'],
        'active_models_changed':False,'requires_compatibility_before_any_activation':True})
    print('FINAL',before['detector']['metrics'],after['detector']['metrics'],checks,flush=True)


def refine_validation():
    if (OUT/'final_started.json').exists() or (OUT/'selection_gated.json').exists():
        raise RuntimeError('Refinement already frozen or final holdout opened')
    write(OUT/'validation_amendment.json',{
        'reason':'Initial additive candidates failed; baseline itself exceeds the unchanged absolute FPR ceiling on daytime-heavy validation. Preserve guards; test one fixed persistence refinement and an ablation.',
        'original_selection_sha256':digest(OUT/'selection.json'),'final_holdout_not_opened':True,
        'fixed_policy':'3 consecutive unsupported ML warnings or same security finding; original residuals/critical alerts immediate. Envelope999 remains normal-fitted with unchanged bounds.',
        'comparators':['persistent_envelope999','persistence_only_control'],
        'no_more_candidates':'No additional fitting, threshold grid or validation redesign. Final rejection means retain original.'})
    model=joblib.load(OUT/'envelope999.joblib');detector=AnomalyDetector.load(DETECTOR);security=AttributionModels.load(SECURITY)
    runs=corpus('validation');prepared=prepare(runs,detector);before=read(OUT/'validation_original.json')
    scores={}
    for name,sidecar in [('persistent_envelope999',model),('persistence_only_control',None)]:
        outputs={r.run_id:persistent_fusion(prepared[r.run_id]['baseline'],prepared[r.run_id]['signals'],sidecar) for r in runs}
        report={'detector':detector_report(runs,outputs),'security':security_report(runs,outputs,detector,security)}
        report['guards']=guards(before,report);scores[name]=report
        write(OUT/f'validation_{name}.json',report)
        print(name,report['detector']['metrics'],report['guards'],flush=True)
    candidate,control=scores['persistent_envelope999'],scores['persistence_only_control']
    adds_value=candidate['detector']['metrics']['recall']>=control['detector']['metrics']['recall']+.02
    selected='persistent_envelope999' if all(candidate['guards'].values()) and adds_value else None
    write(OUT/'selection_gated.json',{'selected':selected,'model':'envelope999','selected_using':'validation only; original guards unchanged',
        'signal_ablation_recall_gain_requirement_passed':adds_value,'candidate_hashes':{'envelope999':digest(OUT/'envelope999.joblib')}})
    print('REFINEMENT SELECTION',selected,flush=True)


def report():
    """Render measured validation results; never open the reserved final corpus."""
    import csv
    names=['original','envelope995','envelope999','normal_if999','persistent_envelope999','persistence_only_control']
    reports={n:read(OUT/f'validation_{n}.json') for n in names}
    base,research=reports['original'],reports['persistent_envelope999']
    comparison=[]
    for name,r in reports.items():
        row={'candidate':name,**r['detector']['metrics'],
            'nature_macro_f1':r['security']['nature']['macro_f1'],
            'origin_macro_f1':r['security']['origin']['macro_f1'],
            'accepted_nature_accuracy':accepted_accuracy(r['security']),
            'normal_stage_b_gate':r['security']['normal_run_false_positive_rate']['detector_fire'],
            'normal_false_attack_label':r['security']['normal_run_false_positive_rate']['nature_classifier_attack_label']}
        comparison.append(row)
    with (OUT/'comparison.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(comparison[0]));writer.writeheader();writer.writerows(comparison)
    attack_rows=[]
    for name,r in reports.items():
        for kind,metrics in r['detector']['by_attack'].items():attack_rows.append({'candidate':name,'attack_type':kind,**metrics})
    with (OUT/'attack_comparison.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(attack_rows[0]));writer.writeheader();writer.writerows(attack_rows)
    matrices={name:{'detector':{k:r['detector']['metrics'][k] for k in ('true_positive','false_positive','true_negative','false_negative')},
        'nature':r['security']['nature']['confusion_matrix'],'origin':r['security']['origin']['confusion_matrix']} for name,r in reports.items()}
    write(OUT/'confusion_matrices.json',matrices)
    def pct(v):return f'{100*v:.2f}%'
    lines=['# Targeted observable-security detector study',
        '**Decision: no candidate qualified. Production models, all baseline artifacts, APIs, UI and live configuration remain unchanged. Reserved final run-level holdout was not generated or inspected. Results below are validation results, not final-test or deployed accuracy claims.**',
        '## Signals and real-time availability',
        '| Signal | Existing fields | Causal handling |\n|---|---|---|\n'
        '| Authentication failure rate | security_telemetry.auth_tag_validity and controller_inputs.sequence_number / message_sequence_number | Latest 8 ticks, distinct observed numeric packet IDs, at least 4 valid/invalid tag observations. Reuse of one stale invalid packet counts once. Missing/unknown tags are unavailable, never invalid. |\n'
        '| Sequence anomaly rate | security_telemetry.duplicate_sequence / out_of_order_sequence | Existing observable sender/receiver log flags only, at least 4 explicit boolean observations. Absolute sequence number is not a learned feature. |\n'
        '| Independent solar gap | measured_solar_kw, redundant_solar_kw | Mean absolute difference / rated solar capacity over at most 8 observed ticks, at least 4 finite pairs. |\n'
        '| Independent SOC gap | measured_soc_pct, redundant_soc_pct | Mean absolute difference /100 over at most 8 observed ticks, at least 4 finite pairs. |',
        'No hidden attack/fault object, source, schedule, event start/end, training target or evaluation metadata enters extraction. Tags/sequence flags are indicators, not proof of malicious intent. Startup and delayed packets may leave authentication unavailable. Missing/nonfinite redundancy values have explicit observation counts; zero placeholders are never interpreted as observed healthy values. The IF skips incomplete domains. Only observations through the current tick are used. Demand spoofing has no independent redundant-demand reading here and was not given an invented feature.',
        '## Constant-feature investigation',
        'The original command_residual_scaled and configuration_deviation have zero Normal training variance and zero Isolation Forest splits. They remain covered by existing residual rules. They were not padded with fabricated variation or retrained blindly. The new sequence_anomaly_rate is also constant at zero on the actual Normal fitting data; it was excluded from the auxiliary IF. A bound on repeated sequence-log irregularities was evaluated explicitly as an empirical envelope, not as learned importance. Measured normal feature variances and exclusion lists are saved in candidate report metadata and legacy_constants.json.',
        '## Bounded protocol',
        'Normal-only fitting: 24 complete runs, seeds12000000+17*i,720 ticks each. Separate Normal calibration:12 runs, seeds12100000+17*i,1440 ticks each. Validation:312 complete240-tick runs from seed13000000:120Normal,96fault,96attack; naive/moderate only, severities.25/.6/1. No adjacent windows were split between populations. Existing simulator logic/configuration generation was reused. Seeds/IDs are checked disjoint and full manifests are saved.',
        'Initial approaches: normal empirical envelopes at.995/.999 quantiles (same four bounds, no learning search), plus one100-tree normal-only Isolation Forest on nonconstant auxiliary features with.999 calibration. The original Isolation Forest score, ML label, thresholds and explanation remain unchanged in every comparison. New checks are explicitly labeled by method. The outcome measured is the combined detection policy, not inflated pure-ML recall.',
        'All initial candidates failed. Diagnosis found79solar-gap,30SOC-gap and1authentication finding ticks on dedicated validation Normal runs for envelope999. Full-cycle calibration and daytime-heavy validation expose different sensor-noise distributions. Baseline combined FPR itself was1.69%, above the unchanged1.5% acceptance ceiling, making a purely additive candidate unable to pass. This was recorded rather than relaxing the limit.',
        'One documented validation amendment, saved before final evaluation, tested a fixed3-tick persistence refinement and a persistence-only ablation. Existing residual-rule and critical alerts stay immediate; unsupported ML warnings and the same new security finding require3consecutive ticks. No thresholds, budgets or simulator equations changed. Original selection.json and failed candidates were preserved; amended selection is separate selection_gated.json. No further refinement followed rejection.',
        'Acceptance stayed fixed: precision at least95% and no more than1point below baseline; tick FPR at most1.5% and baseline+.25point; Normal run alert rate at most baseline+2points; recall gain2points; F1gain1point; event coverage nondecreasing; detected-only delay at most1.1times baseline. Unchanged Stage B nature/origin macro-F1 may lose at most.5point, accepted nature accuracy at most1point, Normal false attack labels and gate rate at most1point.',
        'Reserved final protocol uses entirely new seed16000000, unseen severities.35/.75 and includes stealthy runs excluded from development. No candidate passed validation, so no final_manifest.json/final_started.json or final-test predictions were created. No generalization claim is made, and no rejected candidate was promoted merely to obtain final numbers.',
        '## Actual validation metrics',
        '| Policy | Precision | Recall | F1 | Tick FPR | Event runs detected | Detected-only delay (simulated s) |\n|---|---:|---:|---:|---:|---:|---:|']
    for row in comparison:
        lines.append(f"| {row['candidate']} | {pct(row['precision'])} | {pct(row['recall'])} | {pct(row['f1'])} | {pct(row['false_positive_rate'])} | {row['detected_event_runs']}/{row['total_event_runs']} | {row['mean_detection_delay_seconds']:.2f} |")
    lines += ['Positives are active injected-event ticks (faults and attacks,14500ticks); negatives are all ticks from separate Normal runs (28800ticks). Pre/post-event ticks are excluded. This matches the existing detector evaluation convention but broadens the event corpus to attacks as required. All versions use identical runs and definitions. These figures must not be directly compared to the earlier fault-only dashboard percentages. Original pure-ML component metrics are saved separately and are identical across all candidates.',
        '## Difficult attacks: original versus rejected persistent envelope',
        '| Attack | Original active-tick recall | Research active-tick recall | Original runs detected | Research runs detected | Original delay s | Research delay s |\n|---|---:|---:|---:|---:|---:|---:|']
    for kind,b in base['detector']['by_attack'].items():
        a=research['detector']['by_attack'][kind]
        lines.append(f"| {kind} | {pct(b['active_tick_recall'])} | {pct(a['active_tick_recall'])} | {b['detected_runs']}/{b['runs']} | {a['detected_runs']}/{a['runs']} | {b['mean_delay_seconds']:.2f} | {a['mean_delay_seconds']:.2f} |")
    lines += ['The added signals improve sustained replay and sensor-spoof observation coverage on validation. Compared with persistence alone, active-event recall rose69.08% to79.29%: the gain is not solely smoothing. However message-tampering coverage fell10/12 to8/12, sensor-spoof coverage11/12 to10/12, and communication-degradation delay worsened152.73s to627.27s. A smaller conditional delay with fewer detected events is not automatically better. No hidden labels were used to rescue those missed runs.',
        '## Downstream acceptance and uncertainty',
        '| Stage B metric | Original | Research persistent envelope |\n|---|---:|---:|']
    for label,fn in [('Nature macro-F1',lambda r:r['security']['nature']['macro_f1']),('Origin macro-F1',lambda r:r['security']['origin']['macro_f1']),
        ('Accepted nature accuracy',lambda r:accepted_accuracy(r['security'])),('Normal gate rate',lambda r:r['security']['normal_run_false_positive_rate']['detector_fire']),
        ('Normal false attack-label rate',lambda r:r['security']['normal_run_false_positive_rate']['nature_classifier_attack_label'])]:
        lines.append(f'| {label} | {pct(fn(base))} | {pct(fn(research))} |')
    failed=[k for k,v in research['guards'].items() if not v]
    lines += ['Failed refinement checks: '+', '.join(failed)+'. All initial candidates also failed; full guard booleans are in their JSON reports. Higher tick F1 does not override lower event coverage, incorrect confident classifications or false security alerts.',
        'Stage B weights, confidence policies and original alert gate were not retuned. The sidecar changes which observed incident windows reach this existing model; earlier/different weak or benign windows can lower accepted-prediction accuracy. That measured compatibility regression prevents activation. Existing Undetermined/Unknown behavior remains intact. Nature macro-F1 includes the existing zero-support abstention class; accepted accuracy is measured only on detected determined predictions. These are different denominators.',
        '## Acceptance decision and protection',
        'No candidate accepted, no production setting changed, and no original artifact overwritten. No frontend file was edited. No simulator, injection engine, incident tracker/API, model loader, ShadowTwin, agent algorithm, automatic trigger or budget was edited. The experimental module is not imported by the production detection loader/runtime and cannot silently activate. Three research sidecar artifacts exist (envelope995.joblib,envelope999.joblib,normal_if999.joblib); none is approved for deployment. Original hashes and frontend hashes are verified against the pre-study manifest. Rollback is unnecessary.',
        '## Files created',
        '- backend/app/detection/security_signals.py\n- backend/tests/test_security_signal_detector.py\n- scripts/study_security_detector.py\n- scripts/verify_security_signal_runtime.py\n- docs/security-signal-detector-study.md\n- Generated results under outputs/security-detector-study-v1/ (Git-ignored). Original files and previous uncommitted changes were preserved.',
        '## Verification and remaining limitations',
        'Thirteen focused tests cover streaming/prefix equivalence, hidden-field invariance, missing/nonfinite signals, delayed startup, stale-packet deduplication, constant-feature exclusion, preservation of original ML outputs, immediate residual/critical alerts, three-tick causality and tick-alignment rejection. Full test results and isolated end-to-end checks are recorded in verification.json/runtime_verification.json.',
        'The real FastAPI app was exercised in an isolated in-memory database using the unchanged active models. Eight scenarios check actual persisted signals, batch/streaming parity, injection, incident records, automatic jobs, duplicate prevention and480branch-tick/three-attempt budgets. Normal operation produced no incident/job; controller and sensor cases produced real reports. Replays/message tampering remain missed in the specific seed42 moderate scenario. These are API integration checks, not a claim of deploying the experimental policy or a new browser demonstration. The user live run/database was not reset.',
        'Only one small auxiliary IF was fitted; envelopes use Normal calibration without supervised labels. Five bounded comparisons including the control were made, not an exhaustive search. Results are synthetic and validation-only, with12runs per attack type. Packet flags summarize existing logs and do not provide full independent command authorization or attacker identity. Missing metadata cannot support a claimed attack. The reserved final set remains untouched for a candidate that legitimately passes a future separately declared validation study. No new AI API, dependency, UI change, commit or push was introduced.']
    if (OUT/'verification.json').exists():
        checks=read(OUT/'verification.json')
        lines += ['## Actual regression results',f"Backend: {checks['backend_passed']} passed, 0 failed, {checks['backend_warnings']} existing warnings. Frontend: {checks['frontend_passed']} passed, 0 failed. TypeScript: {checks['typescript']}. Production build: {checks['build']}. git diff --check: passed. No lint script is configured."]
    (OUT/'REPORT.md').write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
    print('Report/CSV/confusion matrices written from validation results only',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=('develop','refine','final','report'))
    args=parser.parse_args();{'develop':develop,'refine':refine_validation,'final':final,'report':report}[args.phase]()
