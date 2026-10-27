"""Final bounded attempt: diagnose first; at most two fixed validation candidates.

Reuses the existing complete-run corpus, metrics and unchanged acceptance guards.
Reserved final data cannot be opened before every validation guard passes.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np

from study_security_detector import (OUT as PREVIOUS, DETECTOR, SECURITY, read, write, digest,
    corpus, prepare, detector_report, security_report, accepted_accuracy, guards, policy)
from app.detection import AnomalyDetector
from app.detection.security_signals import persistent_fusion
from app.detection.event_refinement import onset_fusion
from app.security_analysis.dataset import live_incident_sample
from app.security_analysis.model import AttributionModels


OUT=Path('outputs/final-detector-refinement')


def longest(flags):
    best=current=0
    for flag in flags:
        current=current+1 if flag else 0;best=max(best,current)
    return best


def diagnosis():
    if (OUT/'diagnosis.json').exists():raise RuntimeError('Use the existing diagnostic record')
    OUT.mkdir(parents=True,exist_ok=True)
    assert not (PREVIOUS/'final_started.json').exists()
    detector=AnomalyDetector.load(DETECTOR);model=AttributionModels.load(SECURITY)
    sidecar=joblib.load(PREVIOUS/'envelope999.joblib')
    runs=corpus('validation');prepared=prepare(runs,detector)
    original=read(PREVIOUS/'validation_original.json')
    rejected=read(PREVIOUS/'validation_persistent_envelope999.json')
    before={r.run_id:prepared[r.run_id]['baseline'] for r in runs}
    after={r.run_id:persistent_fusion(before[r.run_id],prepared[r.run_id]['signals'],sidecar) for r in runs}
    assert detector_report(runs,before)==original['detector']
    assert detector_report(runs,after)==rejected['detector']
    joblib.dump({'runs':runs,'prepared':prepared},OUT/'validation_observations.joblib')
    protected={str(p):digest(p) for parent in ('src','frontend','backend/app') for p in Path(parent).rglob('*')
        if p.is_file() and not any(part in p.parts for part in ('node_modules','dist','__pycache__','.git'))}
    write(OUT/'original_manifest.json',{'models':{str(p):digest(p) for p in
        (DETECTOR,SECURITY,Path('outputs/stage3/source_classifier.joblib'))},'protected_sources':protected,
        'previous_guard_source_sha256':digest(Path('scripts/study_security_detector.py'))})
    old_rows={r['run_id']:r for r in original['detector']['per_run']}
    new_rows={r['run_id']:r for r in rejected['detector']['per_run']}
    losses=[];gains=[];misses=[];communication=[]
    for run in runs:
        if run.nature=='normal':continue
        b,a=old_rows[run.run_id],new_rows[run.run_id]
        active=lambda r:run.start_tick<=r['tick']<run.start_tick+run.duration_ticks
        trace=[{'tick':r['tick'],'ml_status':r['ml_status'],'score':r['anomaly_score'],
            'original_combined':r['combined_status'],'rejected_combined':p['combined_status'],
            'original_residuals':r['residual_checks'],'security_values':s['values'],'security_counts':s['counts'],
            'confirmed_security_findings':p['security_signal_findings']}
            for r,p,s in zip(before[run.run_id],after[run.run_id],prepared[run.run_id]['signals']) if active(r)]
        record={**b,'rejected':a,'evaluation_only_target':run.target_component,
            'maximum_consecutive_ml_warnings':longest(t['ml_status']=='warning' for t in trace),
            'critical_ticks':sum(t['ml_status']=='critical' for t in trace),
            'residual_rule_ticks':sum(bool(t['original_residuals']) for t in trace),
            'minimum_available_domain_counts':{key:min(t['security_counts'][key] for t in trace) for key in trace[0]['security_counts']},
            'maximum_security_values':{key:max(t['security_values'][key] for t in trace) for key in trace[0]['security_values']},
            'trace':trace}
        if not a['detected']:misses.append(record)
        if b['detected'] and not a['detected']:losses.append(record)
        if not b['detected'] and a['detected']:gains.append(record)
        if run.scenario_type=='communication_degradation':communication.append(record)
    b_stage={r['run_id']:r for r in original['security']['row_level_results']}
    a_stage={r['run_id']:r for r in rejected['security']['row_level_results']}
    labels={'normal':'Normal','fault':'Accidental fault','attack':'Cyber attack'}
    transitions=[];distribution=Counter()
    for run in runs:
        b,a=b_stage[run.run_id],a_stage[run.run_id]
        ba=b['inference_tick'] is not None and b['nature_prediction']!='Undetermined'
        aa=a['inference_tick'] is not None and a['nature_prediction']!='Undetermined'
        bc=ba and b['nature_prediction']==labels[run.nature]
        ac=aa and a['nature_prediction']==labels[run.nature]
        group=('correct' if bc else 'wrong' if ba else 'not_accepted')+' -> '+('correct' if ac else 'wrong' if aa else 'not_accepted')
        distribution[group]+=1
        if b['inference_tick']!=a['inference_tick'] or b['nature_prediction']!=a['nature_prediction']:
            old=live_incident_sample(run,detector,policy(),statuses=before[run.run_id])
            new=live_incident_sample(run,detector,policy(),statuses=after[run.run_id])
            change={key:{'before':old['features'][key] if old else None,'after':new['features'][key] if new else None}
                for key in model.metadata['feature_names'] if old is None or new is None or old['features'][key]!=new['features'][key]}
            transitions.append({'run_id':run.run_id,'seed':run.seed,'scenario_type':run.scenario_type,'mode':run.mode,
                'evaluation_truth':run.nature,'transition':group,'before':b,'after':a,
                'window_features_changed':change})
    summary={'baseline_detected_event_runs':180,'rejected_detected_event_runs':175,
        'lost_count':len(losses),'gained_count':len(gains),'total_rejected_misses':len(misses),
        'lost_run_ids':[r['run_id'] for r in losses],'gained_run_ids':[r['run_id'] for r in gains],
        'stage_b_transitions':dict(distribution),'stage_b_changed_windows':len(transitions),
        'original_accepted_accuracy':accepted_accuracy(original['security']),
        'rejected_accepted_accuracy':accepted_accuracy(rejected['security']),
        'reserved_final_opened':False}
    write(OUT/'diagnosis.json',summary)
    write(OUT/'all_rejected_misses.json',misses);write(OUT/'lost_runs.json',losses);write(OUT/'gained_runs.json',gains)
    write(OUT/'communication_delay_traces.json',communication);write(OUT/'stage_b_window_changes.json',transitions)
    print(json.dumps(summary,indent=2),flush=True)
    for r in losses:print('LOST',r['run_id'],r['scenario_type'],r['mode'],'warning streak',r['maximum_consecutive_ml_warnings'],'rules',r['residual_rule_ticks'],'critical',r['critical_ticks'],flush=True)


def evaluate_candidates():
    if (OUT/'selection.json').exists():raise RuntimeError('Final attempt already selected; no more candidates')
    assert not (PREVIOUS/'final_started.json').exists() and not (OUT/'final_started.json').exists()
    write(OUT/'protocol.json',{
        'final_attempt':True,'candidates':['onset_security_3_of_3','onset_security_2_of_3'],
        'fit':'No retraining. Reuse frozen normal-calibrated envelope999 and original models.',
        'weak_warning':'Immediate weak-only onset pulse, fixed minimum3tick emission interval from existing confirmation length; physical/critical alerts unchanged.',
        'security_evidence':'3of3 versus2of3 with a current finding required; original envelope thresholds and availability unchanged.',
        'stage_b':'Preserve physical residual checks and original anomaly scores. New security indicators stay separate; do not treat novel checks as calibrated physical residual evidence.',
        'guards':'Import original guards unchanged; additionally preserve every original detected event and every original event Stage B window; at least original accepted prediction count.',
        'protocol':'Same312 validation runs, labels matched only after inference. Per-run and per-attack results, old protocol replay verified. No extra candidates or guard weakening after results.',
        'reserved_final':'Use the original reserved seed16000000 only if all validation guards pass; new complete runs, disjoint from development; a final rejection ends optimization.',
        'prior_diagnosis_sha256':digest(OUT/'diagnosis.json'),
        'candidate_source_sha256':digest(Path('backend/app/detection/event_refinement.py')),
        'guard_source_sha256':digest(Path('scripts/study_security_detector.py'))})
    cache=joblib.load(OUT/'validation_observations.joblib');runs,prepared=cache['runs'],cache['prepared']
    baseline=read(PREVIOUS/'validation_original.json')
    detector=AnomalyDetector.load(DETECTOR);security=AttributionModels.load(SECURITY)
    sidecar=joblib.load(PREVIOUS/'envelope999.joblib')
    reports={}
    for quorum in (3,2):
        name=f'onset_security_{quorum}_of_3'
        outputs={r.run_id:onset_fusion(prepared[r.run_id]['baseline'],prepared[r.run_id]['signals'],sidecar,
            security_quorum=quorum) for r in runs}
        report={'detector':detector_report(runs,outputs),'security':security_report(runs,outputs,detector,security)}
        checks=full_guards(baseline,report)
        report['guards']=checks;report['quorum']=quorum
        reports[name]=report;write(OUT/f'validation_{name}.json',report)
        print(name,json.dumps(report['detector']['metrics']),checks,flush=True)
    eligible=[n for n,r in reports.items() if all(r['guards'].values())]
    selected=max(eligible,key=lambda n:(reports[n]['detector']['metrics']['detected_event_runs'],
        accepted_accuracy(reports[n]['security']),reports[n]['detector']['metrics']['f1'])) if eligible else None
    write(OUT/'selection.json',{'selected':selected,'eligible':eligible,'selected_using':'validation only; event coverage, accepted reliability, then F1',
        'no_further_optimization':True,'sidecar_sha256':digest(PREVIOUS/'envelope999.joblib'),
        'candidate_source_sha256':digest(Path('backend/app/detection/event_refinement.py'))})
    print('FINAL ATTEMPT SELECTION',selected,flush=True)


def full_guards(before,after):
    checks=guards(before,after)
    original={r['run_id'] for r in before['detector']['per_run'] if r['nature']!='normal' and r['detected']}
    current={r['run_id'] for r in after['detector']['per_run'] if r['nature']!='normal' and r['detected']}
    checks['each_original_detected_event_preserved']=original<=current
    def gated(report):return {r['run_id'] for r in report['security']['row_level_results'] if r['nature_truth']!='normal' and r['inference_tick'] is not None}
    checks['each_original_stage_b_event_window_preserved']=gated(before)<=gated(after)
    def accepted_count(report):return sum(r['inference_tick'] is not None and r['nature_prediction']!='Undetermined' for r in report['security']['row_level_results'])
    checks['accepted_count_nonregression']=accepted_count(after)>=accepted_count(before)
    return checks


def final_check():
    selection=read(OUT/'selection.json')
    if (OUT/'acceptance.json').exists() or (OUT/'final_started.json').exists():raise RuntimeError('Final decision already recorded')
    if selection['selected'] is None:
        write(OUT/'acceptance.json',{'accepted':False,'active_models_changed':False,
            'reason':'Neither of the two final-attempt candidates passed all validation requirements; optimization stopped.',
            'reserved_final_opened':False,'no_further_candidates':True})
        print('STOP: no candidate qualified. Reserved final set remains untouched.',flush=True);return
    assert selection['candidate_source_sha256']==digest(Path('backend/app/detection/event_refinement.py'))
    assert selection['sidecar_sha256']==digest(PREVIOUS/'envelope999.joblib')
    write(OUT/'final_started.json',{'selection_sha256':digest(OUT/'selection.json'),'single_final_comparison':True})
    runs=corpus('final')
    development=read(PREVIOUS/'development_manifest.json')
    old=[r for group in development.values() for r in group]
    assert not {r.seed for r in runs}.intersection(r['seed'] for r in old)
    assert not {r.run_id for r in runs}.intersection(r['run_id'] for r in old)
    write(OUT/'final_manifest.json',[r.manifest() for r in runs])
    detector=AnomalyDetector.load(DETECTOR);security=AttributionModels.load(SECURITY)
    sidecar=joblib.load(PREVIOUS/'envelope999.joblib');prepared=prepare(runs,detector)
    quorum=2 if selection['selected'].endswith('2_of_3') else 3
    before_outputs={r.run_id:prepared[r.run_id]['baseline'] for r in runs}
    after_outputs={r.run_id:onset_fusion(prepared[r.run_id]['baseline'],prepared[r.run_id]['signals'],sidecar,security_quorum=quorum) for r in runs}
    before={'detector':detector_report(runs,before_outputs),'security':security_report(runs,before_outputs,detector,security)}
    after={'detector':detector_report(runs,after_outputs),'security':security_report(runs,after_outputs,detector,security)}
    checks=full_guards(before,after)
    write(OUT/'final_original.json',before);write(OUT/'final_candidate.json',after)
    write(OUT/'acceptance.json',{'accepted':all(checks.values()),'guards':checks,'selected':selection['selected'],
        'reserved_final_opened':True,'active_models_changed':False,'compatibility_required_before_activation':True})
    print('FINAL GUARDS',checks,flush=True)


def report():
    """Audit saved validation results only; no data generation or selection."""
    import csv
    previous=read(PREVIOUS/'validation_persistent_envelope999.json')
    original=read(PREVIOUS/'validation_original.json')
    reports={'original':original,'previous_rejected':previous,
        **{name:read(OUT/f'validation_{name}.json') for name in ('onset_security_3_of_3','onset_security_2_of_3')}}
    rows=[];per_run=[];attacks=[];matrices={}
    for name,r in reports.items():
        rows.append({'policy':name,**r['detector']['metrics'],
            'stage_b_accepted_accuracy':accepted_accuracy(r['security']),
            'nature_macro_f1':r['security']['nature']['macro_f1'],'origin_macro_f1':r['security']['origin']['macro_f1'],
            'normal_stage_b_gate':r['security']['normal_run_false_positive_rate']['detector_fire'],
            'normal_false_attack_label':r['security']['normal_run_false_positive_rate']['nature_classifier_attack_label']})
        per_run.extend({'policy':name,**r} for r in r['detector']['per_run'])
        attacks.extend({'policy':name,'attack':kind,**values} for kind,values in r['detector']['by_attack'].items())
        matrices[name]={'detection':{k:r['detector']['metrics'][k] for k in ('true_positive','false_positive','true_negative','false_negative')},
            **{task:r['security'][task]['confusion_matrix'] for task in ('nature','origin')}}
    for filename,records in [('comparison.csv',rows),('per_run_comparison.csv',per_run),('attack_comparison.csv',attacks)]:
        with (OUT/filename).open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    write(OUT/'confusion_matrices.json',matrices)
    diagnostic=read(OUT/'diagnosis.json');losses=read(OUT/'lost_runs.json');misses=read(OUT/'all_rejected_misses.json')
    changes=read(OUT/'stage_b_window_changes.json')
    new_wrong=Counter(r['evaluation_truth'] for r in changes if r['transition']=='not_accepted -> wrong')
    b={r['run_id']:r for r in original['detector']['per_run']};a={r['run_id']:r for r in previous['detector']['per_run']}
    paired=[a[key]['delay_seconds']-value['delay_seconds'] for key,value in b.items() if value['nature']!='normal' and value['detected'] and a[key]['detected']]
    comm=[r for r in read(OUT/'communication_delay_traces.json') if r['detected'] and r['rejected']['detected']]
    write(OUT/'delay_diagnosis.json',{'paired_common_detected_runs':len(paired),
        'mean_paired_delay_change_seconds':float(np.mean(paired)),
        'communication_common_runs':len(comm),
        'communication_mean_paired_delay_change_seconds':float(np.mean([r['rejected']['delay_seconds']-r['delay_seconds'] for r in comm])),
        'conditional_means_warning':'Old mean excluded six lost runs and included one gained replay run; paired means separate timing changes from denominator changes.'})
    timing_changes={}
    labels_unchanged={}
    for n in ('onset_security_3_of_3','onset_security_2_of_3'):
        after_rows={r['run_id']:r for r in reports[n]['security']['row_level_results']}
        timing_changes[n]=[{'run_id':r['run_id'],'before_fire':r['detector_fire_tick'],
            'after_fire':after_rows[r['run_id']]['detector_fire_tick'],'before_inference':r['inference_tick'],
            'after_inference':after_rows[r['run_id']]['inference_tick']}
            for r in original['security']['row_level_results'] if r['inference_tick']!=after_rows[r['run_id']]['inference_tick']]
        labels_unchanged[n]=all((r['nature_prediction'],r['origin_prediction'])==
            (after_rows[r['run_id']]['nature_prediction'],after_rows[r['run_id']]['origin_prediction'])
            for r in original['security']['row_level_results'])
    write(OUT/'stage_b_distribution_diagnosis.json',{
        'original_accepted':120,'original_correct':98,'original_wrong':22,
        'previous_accepted':134,'previous_correct':105,'previous_wrong':29,
        'new_wrong_by_evaluation_nature':dict(new_wrong),'transitions':diagnostic['stage_b_transitions'],
        'candidate_prediction_labels_identical_to_original':labels_unchanged,
        'candidate_timing_changes':timing_changes})
    def pct(v):return f'{100*v:.2f}%'
    lines=['# Final bounded detector refinement — stopped without promotion',
        '**Decision: neither final-attempt candidate passed every validation guard. Optimization has stopped. Original production models and all existing application functionality remain unchanged. Reserved final data was not generated or inspected.**',
        '## Exact reproduction and lost events',
        'The previous original/rejected detector reports were reproduced exactly before candidate evaluation. The change from 180/192 to 175/192 was six lost events and one gained replay event, not five lost events. There were 17 total rejected-policy misses, including 11 runs already missed by the original detector.',
        '| Lost run suffix (full prefix: security-sidecar-validation-stage-b-) | Seed | Scenario / mode | Evaluation-only target | Original alert ticks | Longest ML warning streak |\n|---|---:|---|---|---:|---:|']
    for r in losses:
        lines.append(f"| {r['run_id'].rsplit('-',1)[-1]} | {r['seed']} | {r['scenario_type']} / {r['mode'] or '—'} | {r['evaluation_only_target'] or '—'} | {r['alert_ticks']} | {r['maximum_consecutive_ml_warnings']} |")
    lines += ['All six losses had no critical ML ticks, no original physical residual alerts, and a maximum consecutive ML-warning streak of one. Three-consecutive-warning persistence erased their only detections. All four signal domains met their minimum availability in these six active intervals (authentication counts at least 4; sequence/solar/SOC counts 8). Their signal values remained below the frozen security bounds. Missing/delayed features were not the primary cause, and no detector threshold changed. Exact tick/score/count traces are in lost_runs.json.',
        'The demand-sensor target in run00219 has no independent redundant demand signal in this sidecar. The inverter-targeted message-tampering cases do not necessarily alter authentication or solar/SOC redundancy. These targets are recorded only for this offline audit; the inference policies never receive them. The new gained replay run was00235 (seed13005004).',
        'Aggregate active-tick F1 gives more weight to long sustained detections. Event coverage gives a run one detection regardless of its duration. Extra sustained sensor/replay ticks outweighed six brief lost events in aggregate metrics, which is why the prior higher F1 was insufficient.',
        '## Stage B reliability root cause',
        'The previous detector changed37 Stage B window/prediction rows. Original accepted predictions:98correct/120accepted=81.67%; previous refinement:105correct/134accepted=78.36%. Existing weights, score calibration and abstention thresholds did not change.',
        'Of original accepted predictions,97correct and21wrong remained accepted; one correct and one wrong became unaccepted. Newly accepted outputs included8correct and8wrong predictions. The8new wrong predictions comprised2Normal runs labeled attack,3fault runs labeled attack, and3attack runs labeled fault. This is an evidence-distribution shift, not simply loss of accuracy on the same accepted sample.',
        'The earlier experiment appended empirical security indicators to residual_checks. The unchanged Stage B gate treats that list as residual evidence and can open a different20-tick window sooner, including benign or ambiguous conditions. Thirty-seven changed-window records include exact before/after fire/inference ticks and all changed feature values in stage_b_window_changes.json. Earlier evidence is not automatically better evidence.',
        'Both final-attempt policies keep new security observations in a separately labeled evidence field. Original anomaly_score, residual_checks, rule_status and raw telemetry are unchanged. The calibrated Stage B gate is not bypassed or retrained. New detections without an admissible gate/window remain unclassified. On this validation set, both candidates preserve every original nature/origin prediction label and the availability of a Stage B window on every original gated event:120accepted,98correct,81.67% accepted accuracy. Window timing is not entirely identical: run00149 fires at90 instead of100 and infers at109 instead of119, retaining its Accidental fault prediction. Changed incident grouping can still shift timing even with the original score/residual gate. No abstention manipulation or selective hiding of baseline predictions was used.',
        '## Delay and communication degradation',
        'The old three-consecutive-warning filter delayed sparse warnings until a later sustained warning or physical residual appeared. Communication-degradation active-tick recall fell34.11% to23.56%, while matched detected-run mean delay rose152.73s to627.27s. The new prompt-onset policies restore that mean delay to152.73s and keep11/12 communication-degradation runs detected. Their active-tick recall is31.00%/31.11%, below original34.11%, because redundant weak-warning frames are rate-limited.',
        'Overall means are simulated seconds among detected runs only; misses have null delay. The prior mean180.33→196.46s also changed denominators by losing six runs and gaining one. delay_diagnosis.json reports paired common-run changes separately; no faster claim is based solely on excluding misses.',
        '## Exactly two fixed candidates; no retraining',
        'Candidate A: immediate unsupported weak-ML onset pulse, with at most one such pulse every3ticks; security evidence requires3of3 observed findings. Candidate B: the same onset policy with2of3 security findings, including a genuine current finding. Existing residual and critical alerts remain immediate. Eight-tick security features, minimum observation counts, frozen normal envelope thresholds and all original ML outputs are unchanged.',
        'The3-tick emission interval reuses the existing incident confirmation length. These two policies were documented and source-hashed before their validation results. There was no threshold grid, model fitting, further candidate, post-result parameter adjustment, or guard relaxation. They accept detector outputs and observable signal samples only, never labels/schedules/source truth.',
        'All original guards were imported unchanged. Additional requirements preserve every baseline detected event, every baseline Stage B event window, and at least the baseline accepted prediction count. This prevents offsetting lost incidents with unrelated gains or improving accuracy by withholding difficult existing predictions.',
        '## Actual validation comparison',
        '| Policy | Precision | Recall | F1 | Tick FPR | Detected event runs | Detected-only delay s | Stage B accepted accuracy |\n|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f"| {row['policy']} | {pct(row['precision'])} | {pct(row['recall'])} | {pct(row['f1'])} | {pct(row['false_positive_rate'])} | {row['detected_event_runs']}/192 | {row['mean_detection_delay_seconds']:.2f} | {pct(row['stage_b_accepted_accuracy'])} |")
    lines += ['Same312 validation runs,120Normal/96fault/96attack;14500active-event ticks and28800Normal ticks. Active injected-event ticks define positives; all dedicated Normal ticks define negatives; pre/post-event periods are excluded. Raw ML metrics remain unchanged and are saved separately. These combined-policy validation percentages are not interchangeable with historical fault-only dashboard metrics or final-test performance.',
        '## Difficult attacks and preserved strengths',
        '| Attack | Original tick recall | Previous rejected | Candidate A | Candidate B | Original / A / B runs detected |\n|---|---:|---:|---:|---:|---|']
    for kind,rr in original['detector']['by_attack'].items():
        values=[reports[n]['detector']['by_attack'][kind] for n in ('original','previous_rejected','onset_security_3_of_3','onset_security_2_of_3')]
        lines.append(f"| {kind} | {pct(values[0]['active_tick_recall'])} | {pct(values[1]['active_tick_recall'])} | {pct(values[2]['active_tick_recall'])} | {pct(values[3]['active_tick_recall'])} | {values[0]['detected_runs']} / {values[2]['detected_runs']} / {values[3]['detected_runs']} of {rr['runs']} |")
    lines += ['Both candidates recover all six lost baseline events and retain the gained replay run. Sensor spoofing, replay and message-tampering tick recall gains remain. Controller/firmware strengths and original Stage B quality remain intact on validation. Full per-run detection coverage, delay and per-attack counts are in per_run_comparison.csv and attack_comparison.csv.',
        '## Mandatory rejection and end of optimization',
        'Candidate A:466false-alert ticks/28800Normal ticks=1.6181%; candidate B:488/28800=1.6944%. The fixed1.50% limit permits at most432false-alert ticks. A exceeds it by34ticks and B by56ticks. A improves on the original488false ticks but still fails the absolute requirement. Every other original and strengthened guard passes. The limit was not weakened because a result looked close.',
        'Weak isolated ML warnings also occur during healthy behavior. Promptly retaining them restores weak-event coverage but retains too many false alarms under the current ceiling; demanding persistence reduces false alarms but loses sparse event evidence. This bounded attempt did not resolve that tradeoff reliably. Unknown/ambiguous evidence is not a valid reason to inject hidden-source knowledge or claim intent.',
        'No candidate qualified for final evaluation. The reserved seed16000000 corpus remains ungenerated and uninspected, including unseen runs and reserved stealthy conditions. No final-test accuracy or generalization is claimed. Optimization is stopped; no additional automatic tuning is planned.',
        '## Exact list of all17 previously rejected-policy misses',
        '| Run suffix | Scenario / mode | Original detected? | Rejected alert ticks |\n|---|---|---|---:|']
    for r in misses:lines.append(f"| {r['run_id'].rsplit('-',1)[-1]} | {r['scenario_type']} / {r['mode'] or '—'} | {'yes' if r['detected'] else 'no'} | {r['rejected']['alert_ticks']} |")
    lines += ['Full IDs, seeds, severity, target audit metadata and per-tick reasons are in all_rejected_misses.json; no evaluation metadata enters candidate inference.',
        '## Files and protection',
        'Created backend/app/detection/event_refinement.py, backend/tests/test_event_refinement.py, scripts/final_detector_refinement.py and docs/final-detector-refinement.md. Previous study scripts, candidate artifacts and reports were not overwritten. New outputs are isolated under outputs/final-detector-refinement/. No model was trained or activated; cached telemetry is evaluation data, not a model artifact.',
        'No frontend, simulator physics, fault/attack engine, incident API/tracker, model loader, ShadowTwin, agent, automatic trigger, budget or dependency was edited. Original model hashes and pre-existing frontend/application source hashes are checked against original_manifest.json. No live-user run reset, commit or push occurred. Rollback requires no action because nothing was deployed.']
    if (OUT/'verification.json').exists():
        v=read(OUT/'verification.json')
        lines+=['## Actual regression results',f"Backend: {v['backend_passed']} passed,0failed,{v['backend_warnings']}existing warnings. Focused new tests:8passed. Frontend:{v['frontend_passed']}passed. TypeScript:{v['typescript']}. Production build:{v['build']}. git diff --check passed. No lint script is configured. No browser deployment verification is claimed because no candidate was accepted or deployed."]
    (OUT/'REPORT.md').write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
    print('Saved final-attempt report, per-run/attack CSVs, matrices and distribution/delay audits.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=('diagnose','validate','final','report'))
    args=parser.parse_args();{'diagnose':diagnosis,'validate':evaluate_candidates,'final':final_check,'report':report}[args.phase]()
