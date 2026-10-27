"""Bounded, run-disjoint reliability experiment. Run with PYTHONPATH=backend.

Phases are deliberately separate: reproduce, develop, then one frozen final test.
Nothing in this script changes the live server or overwrites original artifacts.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from app.detection import AnomalyDetector
from app.detection.dataset import normal_runs, fault_runs, simulate_run, validate_partitions
from app.detection.evaluation import evaluate as anomaly_evaluate
from app.detection.model import Thresholds
from app.localization import SourceLocalizer
from app.localization.dataset import partition_runs
from app.localization.features import FEATURE_NAMES as SOURCE_FEATURES
from app.localization.evaluation import evaluate as source_evaluate
from app.localization.model import ConfidencePolicy
from app.security_analysis.dataset import AlertPolicy, generate_runs, live_incident_sample
from app.security_analysis.evaluation import evaluate as security_evaluate
from app.security_analysis.model import AttributionModels, AbstentionPolicy

ROOT = Path('outputs/accuracy-optimization')
BASE = {'anomaly': Path('outputs/stage2/anomaly.joblib'),
        'source': Path('outputs/stage3/source_classifier.joblib'),
        'security': Path('outputs/step5/candidates/regular/selected.joblib'),
        'stealth': Path('outputs/step5/candidates/stealth_generalization/selected.joblib')}
CLASSES = {'anomaly': AnomalyDetector, 'source': SourceLocalizer,
           'security': AttributionModels, 'stealth': AttributionModels}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def read(path): return json.loads(path.read_text(encoding='utf-8'))


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def anomaly_ok(before, after):
    b, a = before['performance']['ml'], after['performance']['ml']
    return (a['f1'] >= b['f1'] + .02 and a['recall'] >= b['recall'] + .02
            and a['precision'] >= .95 and a['false_positive_rate'] <= .015
            and a['false_positive_rate'] <= b['false_positive_rate'] + .0075
            and a['detected_fault_runs'] >= b['detected_fault_runs']
            and a['mean_detection_delay_seconds'] <= b['mean_detection_delay_seconds'] * 1.1)


def source_ok(b, a):
    return (a['macro_f1'] >= b['macro_f1'] + .005
            and a['accepted_accuracy'] >= b['accepted_accuracy'] - .01
            and a['per_class']['normal']['precision'] >= b['per_class']['normal']['precision']
            and a['per_class']['normal']['recall'] >= b['per_class']['normal']['recall']
            and a['per_class']['inverter']['recall'] >= b['per_class']['inverter']['recall'] + .01
            and all(a['per_class'][c]['recall'] >= b['per_class'][c]['recall'] - .01
                    for c in ('controller', 'firmware', 'sensor', 'communication')))


def accepted_accuracy(report):
    rows = [r for r in report['row_level_results'] if r['inference_tick'] is not None
            and r['nature_prediction'] != 'Undetermined']
    labels = {'normal':'Normal','fault':'Accidental fault','attack':'Cyber attack'}
    return sum(r['nature_prediction'] == labels[r['nature_truth']] for r in rows) / len(rows) if rows else 0


def security_ok(b, a):
    return (a['nature']['macro_f1'] >= b['nature']['macro_f1'] + .005
            and a['fault_vs_attack']['macro_f1'] >= b['fault_vs_attack']['macro_f1']
            and a['origin']['macro_f1'] >= b['origin']['macro_f1'] - .005
            and accepted_accuracy(a) >= accepted_accuracy(b) - .01
            and a['normal_run_false_positive_rate']['nature_classifier_attack_label']
                <= b['normal_run_false_positive_rate']['nature_classifier_attack_label'] + .01)


def load_models(): return {key:CLASSES[key].load(path) for key,path in BASE.items()}


def security_report(model, runs, detector, policy, samples=None):
    report = security_evaluate(model, runs, detector, alert_policy=policy,
        sample_builder=(lambda run, *_: samples.get(run.run_id)) if samples is not None else live_incident_sample,
        compute_importance=False)
    report['protocol'] = 'live_incident_v1'
    return report


def cache_report(path, factory):
    if path.exists(): return read(path)
    result = factory(); write(path,result); return result


def reproduce(models):
    # Historical test sets are diagnostic references, not the new final holdout.
    original = ROOT/'baseline'
    cache_report(original/'anomaly.json',lambda:anomaly_evaluate(models['anomaly'],normal_runs('test',8),fault_runs()))
    cache_report(original/'source.json',lambda:source_evaluate(models['source'],partition_runs('test')))
    cache = joblib.load('outputs/step5/candidates/observed_samples.joblib')
    for key, folder, samples in (
        ('security','regular',cache['samples']),
        ('stealth','stealth_generalization',joblib.load('outputs/step5/candidates/stealth_observed_samples.joblib')['samples'])):
        saved = read(Path('outputs/step5/candidates')/folder/'held_out_evaluation.json')
        ids = {r['run_id'] for r in saved['row_level_results']}
        runs = [r for r in cache['runs'] if r.run_id in ids]
        assert len(runs)==len(ids)
        cache_report(original/f'{key}.json',lambda:security_report(models[key],runs,models['anomaly'],AlertPolicy(**saved['alert_policy']),samples))
    checks={}
    for key,path,field in (
        ('anomaly','outputs/stage2/evaluation.json','performance'),
        ('source','outputs/stage3/evaluation.json','confusion_matrix'),
        ('security','outputs/step5/candidates/regular/held_out_evaluation.json','nature'),
        ('stealth','outputs/step5/candidates/stealth_generalization/held_out_evaluation.json','nature')):
        checks[key] = read(original/f'{key}.json')[field] == read(Path(path))[field]
        if key in ('security','stealth'):
            for metric in ('origin','fault_vs_attack','detector_coverage','abstention_rate',
                           'normal_run_false_positive_rate','attack_detection_delay_ticks',
                           'nature_recall_by_attack_type'):
                checks[key+'_'+metric]=read(original/f'{key}.json')[metric]==read(Path(path))[metric]
    write(original/'reproduction.json',{'identical_saved_metric_fields':checks,
        'security_reproduction':'Trusted cached observable windows; labels only used by existing evaluator. Cache discards telemetry after extraction; final holdout regenerates real simulation telemetry.',
        'historical_test_status':'Previously inspected/used in earlier project work; not pristine for final selection.'})
    assert all(checks.values()), checks
    print('Historical metrics reproduced exactly',checks,flush=True)


def fresh_detection(partition):
    # Identical generator, whole-run new seeds; no adjacent-window splitting.
    offset = 4100000 if partition=='validation' else 7100000
    n = 12 if partition=='validation' else 20
    normal=[simulate_run(f'accuracy-{partition}-normal-{i}',offset+i,1440) for i in range(n)]
    faulty=[]
    for i,run in enumerate(fault_runs()):
        faulty.append(simulate_run(f'accuracy-{partition}-fault-{i}',offset+100+i,360,
                      run.fault,start_hour=run.config.start_hour))
    return normal,faulty


def source_final():
    old=partition_runs('test')
    return [simulate_run(f'accuracy-final-source-{i}',8100000+i,len(r.telemetry),r.fault,
                         start_hour=r.config.start_hour) for i,r in enumerate(old)]


def protocol():
    value={'version':'accuracy-v1','seed':42,'feature_changes':False,
        'anomaly_candidates':'Frozen IsolationForest; warning quantiles .985/.98/.975/.95 on original normal calibration scores. Critical threshold unchanged.',
        'source_candidates':'Two RF settings: leaf=2 balanced_subsample, leaf=1 balanced; 200 trees/depth16/seed42. Original training CSV only. Original confidence policy retained. One policy-only .60/.10 comparator.',
        'security_candidates':'Nature minimum .54 or .62, margin .08 unchanged, origin .52 unchanged. Same weights/calibration. Select on historical run-disjoint validation only.',
        'anomaly_guards':'ML F1 and recall +.02; precision>=.95; FPR<=.015 AND baseline+.0075; coverage nondecreasing; detected-only delay<=baseline*1.1.',
        'source_guards':'MacroF1+.005; accepted accuracy>=baseline-.01; normal precision/recall nondecreasing; inverter recall+.01; each other class recall>=baseline-.01.',
        'security_guards':'Nature macroF1+.005, binaryF1 nondecreasing, originF1>=baseline-.005, accepted nature accuracy>=baseline-.01, normal attack false rate<=baseline+.01.',
        'final_gate':'Exactly one fresh comparison per frozen selected candidate; fail means retain original, no holdout-driven reselection.',
        'final_seeds':{'detection':7100000,'source':8100000,'security':9100000},
        'stealth':'Also compare dedicated stealth-excluded model with its frozen policy on new stealthy runs; regular model has previously seen stealthy training configurations, so this is separately labeled.',
        'normal_false_alert_tradeoff':'Anomaly tick-level maximum rises from historical .84% to at most 1.5%; this is an explicit bounded tradeoff, not assumed free improvement.'}
    path=ROOT/'protocol.json'
    if path.exists(): assert read(path)==value,'Protocol changed during experiment'
    else: write(path,value)


def develop(models):
    if (ROOT/'selection.json').exists(): raise RuntimeError('Selection already frozen; do not tune after final inspection')
    protocol()
    normal,faulty=fresh_detection('validation')
    validate_partitions(normal,faulty)
    reports={}; candidates={}
    reports['anomaly']={'original':anomaly_evaluate(models['anomaly'],normal,faulty)}
    calibrating=normal_runs('calibration',8)
    scores=np.concatenate([-models['anomaly'].pipeline.score_samples(np.asarray([o.vector() for o in r.observations()])) for r in calibrating])
    for q in (.985,.98,.975,.95):
        name=f'q{q}'
        m=deepcopy(models['anomaly']);m.thresholds=Thresholds(float(np.quantile(scores,q)),m.thresholds.critical)
        m.metadata.update(warning_quantile=q,accuracy_revision='accuracy-v1',selection_scope='validation only')
        candidates['anomaly',name]=m
        reports['anomaly'][name]=anomaly_evaluate(m,normal,faulty)
        print('Anomaly',name,reports['anomaly'][name]['performance']['ml'],flush=True)
    validation=partition_runs('validation')
    reports['source']={'original':source_evaluate(models['source'],validation)}
    table=pd.read_csv('outputs/stage3/source_training_features.csv')
    assert set(table.run_id)=={r['run_id'] for r in models['source'].metadata['training_runs']}
    for leaf,weight in ((2,'balanced_subsample'),(1,'balanced')):
        name=f'leaf{leaf}'
        m=deepcopy(models['source'])
        m.classifier=RandomForestClassifier(n_estimators=200,max_depth=16,min_samples_leaf=leaf,class_weight=weight,random_state=42,n_jobs=1)
        m.classifier.fit(table.loc[:,SOURCE_FEATURES].to_numpy(),table.target.to_numpy())
        m.metadata.update(accuracy_revision='accuracy-v1',training_configuration={'leaf':leaf,'weight':weight,'seed':42,'n_estimators':200,'max_depth':16})
        candidates['source',name]=m;reports['source'][name]=source_evaluate(m,validation)
        print('Source',name,reports['source'][name]['macro_f1'],reports['source'][name]['per_class'],flush=True)
    m=deepcopy(models['source']);m.policy=ConfidencePolicy(.60,.10)
    m.metadata={**m.metadata,'policy':asdict(m.policy),'accuracy_revision':'accuracy-v1'}
    candidates['source','policy60']=m;reports['source']['policy60']=source_evaluate(m,validation)
    cache=joblib.load('outputs/step5/candidates/observed_samples.joblib')
    selection=read(Path('outputs/step5/candidates/regular/selection_before_test.json'))
    ids={r['run_id'] for r in selection['splits']['validation']}
    runs=[r for r in cache['runs'] if r.run_id in ids]
    policy=AlertPolicy(**read(Path('outputs/step5/candidates/regular/held_out_evaluation.json'))['alert_policy'])
    reports['security']={'original':security_report(models['security'],runs,models['anomaly'],policy,cache['samples'])}
    for minimum in (.54,.62):
        name=f'nature{minimum}'
        m=deepcopy(models['security']);m.policy=AbstentionPolicy(minimum,.52,.08)
        m.metadata={**m.metadata,'policy':asdict(m.policy),'accuracy_revision':'accuracy-v1'}
        candidates['security',name]=m
        reports['security'][name]=security_report(m,runs,models['anomaly'],policy,cache['samples'])
        print('Security',name,reports['security'][name]['nature']['macro_f1'],accepted_accuracy(reports['security'][name]),flush=True)
    write(ROOT/'validation.json',reports)
    choices={};guards={'anomaly':anomaly_ok,'source':source_ok,'security':security_ok}
    rank={'anomaly':lambda r:r['performance']['ml']['f1'],'source':lambda r:r['macro_f1'],'security':lambda r:r['nature']['macro_f1']}
    for key in guards:
        eligible=[n for n,r in reports[key].items() if n!='original' and guards[key](reports[key]['original'],r)]
        choice=max(eligible,key=lambda n:rank[key](reports[key][n])) if eligible else 'original'
        choices[key]=choice
        path=ROOT/'candidates'/key/('anomaly.joblib' if key=='anomaly' else 'source_classifier.joblib' if key=='source' else 'selected.joblib')
        (candidates[key,choice] if choice!='original' else models[key]).save(path)
    write(ROOT/'selection.json',{'selected':choices,'selected_before_final':True,
          'candidate_hashes':{key:digest(next((ROOT/'candidates'/key).glob('*.joblib'))) for key in choices}})
    print('FROZEN SELECTION',choices,flush=True)


def final(models):
    selection=read(ROOT/'selection.json')
    marker=ROOT/'final_started.json'
    if marker.exists(): raise RuntimeError('Final holdout already opened; use saved results, no reselection')
    write(marker,{'selection_sha256':digest(ROOT/'selection.json'),'one_final_comparison':True})
    selected={key:CLASSES[key].load(next((ROOT/'candidates'/key).glob('*.joblib'))) for key in selection['selected']}
    for key,m in selected.items():
        assert digest(next((ROOT/'candidates'/key).glob('*.joblib')))==selection['candidate_hashes'][key]
    before={};after={}
    normal,faulty=fresh_detection('final')
    before['anomaly']=anomaly_evaluate(models['anomaly'],normal,faulty)
    after['anomaly']=anomaly_evaluate(selected['anomaly'],normal,faulty)
    runs=source_final();before['source']=source_evaluate(models['source'],runs);after['source']=source_evaluate(selected['source'],runs)
    print('Final detector and source evaluated',flush=True)
    runs=generate_runs(repeats=2,ticks=240,seed=9100000,severities=(.4,.8))
    for r in runs:r.run_id='accuracy-final-'+r.run_id
    write(ROOT/'final_run_manifest.json',[r.manifest() for r in runs])
    policy=AlertPolicy(**read(Path('outputs/step5/candidates/regular/held_out_evaluation.json'))['alert_policy'])
    for name,detector,model,target in [('before',models['anomaly'],models['security'],before),('after',selected['anomaly'],selected['security'],after)]:
        samples={}
        for i,r in enumerate(runs):
            sample=live_incident_sample(r,detector,policy)
            if sample:samples[r.run_id]=sample
            if i%100==0: print('Final security windows',name,i,len(runs),flush=True)
        target['security']=security_report(model,runs,detector,policy,samples)
    stealth=[r for r in runs if r.stealth_level=='stealthy' or r.nature!='attack']
    stealth_policy=AlertPolicy(**read(Path('outputs/step5/candidates/stealth_generalization/held_out_evaluation.json'))['alert_policy'])
    stealth_model=deepcopy(models['stealth']);stealth_model.policy=selected['security'].policy
    # Dedicated artifact has no stealthy training runs. Never fit it on final data.
    before['stealth']=security_report(models['stealth'],stealth,models['anomaly'],stealth_policy)
    after['stealth']=security_report(stealth_model,stealth,selected['anomaly'],stealth_policy)
    write(ROOT/'final_before.json',before);write(ROOT/'final_after.json',after)
    guards={'anomaly':anomaly_ok,'source':source_ok,'security':security_ok}
    accepted={key:selection['selected'][key]!='original' and guard(before[key],after[key]) for key,guard in guards.items()}
    # A security policy change must also preserve dedicated held-out stealth performance.
    if accepted['security']:
        accepted['security']=after['stealth']['nature']['macro_f1']>=before['stealth']['nature']['macro_f1']-.005 and accepted_accuracy(after['stealth'])>=accepted_accuracy(before['stealth'])-.01
    # Detector threshold changes must not regress downstream end-to-end security.
    if accepted['anomaly']:
        accepted['anomaly']=after['security']['nature']['macro_f1']>=before['security']['nature']['macro_f1']-.005 and after['security']['origin']['macro_f1']>=before['security']['origin']['macro_f1']-.005
    write(ROOT/'acceptance.json',{'accepted':accepted,'selection':selection['selected'],
        'originals_preserved':{k:digest(p) for k,p in BASE.items()},'activation_performed':False})
    for key,ok in accepted.items():
        m=selected[key] if ok else models[key]
        folder=ROOT/'accepted'/key
        path=folder/('anomaly.joblib' if key=='anomaly' else 'source_classifier.joblib' if key=='source' else 'selected.joblib')
        m.save(path)
        report=deepcopy(after[key] if ok else before[key])
        report['artifact_sha256']=digest(path)
        report['model_revision']='accuracy-v1' if ok else 'original-retained'
        if key=='anomaly':report['thresholds']=asdict(m.thresholds)
        elif key=='source':report['policy']=asdict(m.policy)
        write(folder/('held_out_evaluation.json' if key=='security' else 'evaluation.json'),report)
        if key=='security':
            write(folder/'stealth_generalization_evaluation.json',after['stealth'] if ok else before['stealth'])
            write(folder/'metadata.json',{'provenance':'accuracy-v1: fresh run-level evaluation; frozen validation-only selection',
                'generator_seed':9100000,'run_count':len(runs),
                'class_run_counts':{nature:sum(r.nature==nature for r in runs) for nature in ('normal','fault','attack')},
                'feature_version':m.metadata['feature_version'],'artifact_sha256':digest(path),
                'dedicated_stealth_report':'Separately evaluated artifact excluded stealthy training runs; not a claim that the regular model excluded them.'})
    print('FINAL ACCEPTANCE',accepted,flush=True)


def report_results(models):
    """Derive comparisons without training, choosing or activating any model."""
    import csv
    before,after=read(ROOT/'final_before.json'),read(ROOT/'final_after.json')
    validation=read(ROOT/'validation.json');decision=read(ROOT/'acceptance.json')
    rows=[]
    def add(task,metric,b,a):rows.append({'task':task,'metric':metric,'before':b,'candidate':a,'active_after':b})
    for method in ('ml','combined','rules'):
        for key in ('precision','recall','f1','false_positive_rate','mean_detection_delay_seconds','detected_fault_runs','total_fault_runs'):
            add('anomaly_'+method,key,before['anomaly']['performance'][method][key],after['anomaly']['performance'][method][key])
    for task in ('security','stealth'):
        for key in ('nature','fault_vs_attack','origin'):add(task,key+'_macro_f1',before[task][key]['macro_f1'],after[task][key]['macro_f1'])
        add(task,'accepted_nature_accuracy',accepted_accuracy(before[task]),accepted_accuracy(after[task]))
        add(task,'detector_coverage',before[task]['detector_coverage'],after[task]['detector_coverage'])
        for key in ('nature','origin'):add(task,key+'_abstention_all_runs',before[task]['abstention_rate'][key],after[task]['abstention_rate'][key])
        for key in ('nature_classifier_attack_label','detector_fire'):add(task,'normal_'+key,before[task]['normal_run_false_positive_rate'][key],after[task]['normal_run_false_positive_rate'][key])
        for key in ('mean_on_detected_attacks','missed_attack_rate','mean_inference_delay_including_post_fire_window'):
            add(task,key,before[task]['attack_detection_delay_ticks'][key],after[task]['attack_detection_delay_ticks'][key])
        for label in ('Normal','Accidental fault','Cyber attack'):
            for key in ('precision','recall','f1-score','support'):
                add(task,label+'_'+key,before[task]['nature']['per_class'][label][key],after[task]['nature']['per_class'][label][key])
        for kind,entry in before[task]['nature_recall_by_attack_type'].items():
            for key in ('detector_fire_rate','attack_label_rate','run_count'):
                add(task,kind+'_'+key,entry[key],after[task]['nature_recall_by_attack_type'][kind][key])
    add('source','macro_f1',before['source']['macro_f1'],after['source']['macro_f1'])
    for label in before['source']['per_class']:
        for key in ('precision','recall','f1-score','support'):
            add('source',label+'_'+key,before['source']['per_class'][label][key],after['source']['per_class'][label][key])
    for task in ('anomaly','source','security','stealth'):
        if task=='anomaly':
            matrices={side:{method:{k:report[task]['performance'][method][k] for k in ('true_positive','false_positive','true_negative','false_negative')} for method in ('ml','rules','combined')} for side,report in (('before',before),('candidate',after))}
        elif task=='source':matrices={side:report[task]['confusion_matrix'] for side,report in (('before',before),('candidate',after))}
        else:matrices={side:{key:report[task][key]['confusion_matrix'] for key in ('nature','fault_vs_attack','origin')} for side,report in (('before',before),('candidate',after))}
        write(ROOT/'confusion_matrices'/f'{task}.json',matrices)
    with (ROOT/'comparison.csv').open('w',newline='',encoding='utf-8') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    tradeoff=[{'candidate':name,**{key:r['performance']['ml'][key] for key in
              ('precision','recall','f1','false_positive_rate','mean_detection_delay_seconds')}}
              for name,r in validation['anomaly'].items()]
    with (ROOT/'threshold_tradeoff.csv').open('w',newline='',encoding='utf-8') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(tradeoff[0]));writer.writeheader();writer.writerows(tradeoff)
    # Resample entire paired runs; never pretend correlated ticks are independent.
    b,a=before['anomaly']['per_run'],after['anomaly']['per_run']
    assert [r['run_id'] for r in b]==[r['run_id'] for r in a]
    def counts(records):
        return np.asarray([[r['evaluated_rows']*r['ml_alert_fraction'] if r['kind']!='normal' else 0,
                            r['evaluated_rows']*r['ml_alert_fraction'] if r['kind']=='normal' else 0,
                            r['evaluated_rows']*(1-r['ml_alert_fraction']) if r['kind']!='normal' else 0] for r in records])
    bc,ac=counts(b),counts(a);rng=np.random.default_rng(73131)
    groups=[np.asarray([i for i,r in enumerate(b) if (r['kind']=='normal')==normal]) for normal in (True,False)]
    deltas=[]
    for _ in range(2000):
        ix=np.concatenate([rng.choice(g,len(g),replace=True) for g in groups])
        bt,bf,bn=bc[ix].sum(axis=0);at,af,an=ac[ix].sum(axis=0)
        deltas.append(2*at/(2*at+af+an)-2*bt/(2*bt+bf+bn))
    interval={'method':'paired complete-run stratified bootstrap, 2000 replicates, seed73131; synthetic generator uncertainty only',
        'candidate_ml_f1_difference_95_percentile_interval':np.quantile(deltas,[.025,.975]).tolist(),
        'limitations':'Small scenario groups; not real-world confidence, not used for selection; a positive F1 interval does not override acceptance failures.'}
    write(ROOT/'uncertainty.json',interval)
    write(ROOT/'comparison.json',{'active_models_changed':False,'acceptance':decision,'metrics':rows,'uncertainty':interval})
    def pct(v):return f'{100*v:.2f}%'
    def table(task,keys):
        selected=[r for r in rows if r['task']==task and r['metric'] in keys]
        return '| Metric | Before | Rejected candidate | Active after |\n|---|---:|---:|---:|\n'+'\n'.join(f"| {r['metric']} | {pct(r['before']) if 'seconds' not in r['metric'] and 'runs' not in r['metric'] else round(r['before'],2)} | {pct(r['candidate']) if 'seconds' not in r['metric'] and 'runs' not in r['metric'] else round(r['candidate'],2)} | {pct(r['active_after']) if 'seconds' not in r['metric'] and 'runs' not in r['metric'] else round(r['active_after'],2)} |" for r in selected)
    lines=['# OriginX accuracy and reliability study',
        '**Status: bounded evaluation completed; no candidate qualified for activation. The requested deployed accuracy improvement was not achieved. Active models, features, thresholds, calibration, UI and live behavior are unchanged.**',
        '## Reproduction and protocol',
        'Historical Stage 2/3 metrics and both Stage B report classifications reproduced exactly. Historical tests have been inspected in prior development and are not pristine final tests. See baseline/reproduction.json. Stage B reproduction uses trusted cached observable windows; the fresh final comparison regenerates real telemetry and live incident windows.',
        'Read protocol.json, validation.json, selection.json and final_started.json for predeclared guards, finite candidates and the selection frozen before final labels were inspected. No reselection or extra training followed final rejection.',
        'Stage 2 normal-only fitting: seeds1000–1023, calibration10000–10007, 1440 ticks. Source fitting: existing 168 complete runs/28106 rows, seeds100000 onward, six classes (normal8640,sensor6012,inverter4994,communication4872,firmware2408,controller1180). Source validation uses the original independent 200000 partition. Only source RF comparators were retrained (200 trees/depth16; leaf2 balanced_subsample or leaf1 balanced). Stage B uses existing calibrated gradient boosting weights; legacy fitting included 515 fired windows, only 5 Normal. Its policy-only comparison used independent cached validation runs from the 841600 corpus. No final rows trained any model.',
        'Fresh final detector: 20 Normal runs (28800 ticks) and 96 fault runs (15360 active ticks), seeds7100000 and7100100 onward. Fresh final source:104 runs, seeds8100000 onward. Security:280 new runs, seeds9101009+17*i, 120normal/64fault/96attack, 240ticks, previously untested severity values .4/.8. Dedicated stealth test:216 runs, including32 stealthy attacks plus184 Normal/fault runs. All predictions precede offline label matching. Final run manifests and full per-run results are saved.',
        'The final detector population deliberately contains more Normal exposure than validation (20 vs12 runs). Precision depends on prevalence. Both before and candidate use exactly the same final population; historical percentages are not directly compared to these fresh-test percentages.',
        '## Diagnosed causes',
        '- Isolation Forest has zero splits on command_residual_scaled and configuration_deviation: both are constant in its Normal training corpus. Residual rules cover these deviations; the headline 29.68% recall is ML alone, while historical combined recall is71.89%. Those are different methods.',
        '- Anomaly features omit existing sequence/authentication and redundant-sensor indicators that Stage B can consume. Stage B cannot classify an event that its upstream incident gate misses. The fresh runtime replay and message-tampering examples produced no alerts; changing the nature threshold cannot fix those misses.',
        '- Normal/weak-fault overlap and abstention both affect source metrics: historical true Normal848 unknown ticks; inverter802 Normal and337 unknown ticks. Inverter delay/severity.6 had zero correct accepted ticks on the historical set. Some injected conditions have little or no observable effect; forcing a fault label is not justified.',
        '- Stage B end-to-end recall is reduced by detector misses, incomplete gated windows and abstention; ambiguous fault/manipulation signatures remain an identifiability limitation. Existing tests demonstrate bit-identical inverter shutdown and actuator-abuse telemetry. Rare Normal fired windows in training and shifted live-aligned windows are additional measured coverage limitations.',
        '## Metric definitions',
        'Anomaly positives are active injected-fault ticks; negatives are dedicated healthy-run ticks; pre/post-fault rows excluded. Delay is simulated seconds among detected runs only, missed runs null. It excludes the separate three-warning-tick incident confirmation. Critical alerts confirm immediately. Stage B adds19 ticks for its20-tick feature window.',
        'Nature macro-F1 averages Normal/fault/attack/Undetermined, including the zero-support abstention class. Fault-versus-attack macro-F1 uses the non-Normal truth subset and includes Undetermined as a third class. These are existing definitions, not interchangeable percentages. Binary confusion matrices omit predictions outside their listed labels (notably Normal); their counts need not sum to all240 historical or160 fresh event runs. Full nature matrices and per-run rows retain those misses. No metric definition was changed.',
        'Stage B detector coverage includes Normal runs in its denominator. The historical2.22% is Normal detector fire rate; Normal attack-label false rate is0%. Source macro-F1 uses the six known classes, with Unknown counted as missed known-class recall. Model scores are not guarantees of source or intent.',
        '## Validation precision-recall tradeoff',
        '| Candidate | Precision | Recall | F1 | Normal false-positive rate |\n|---|---:|---:|---:|---:|\n'+'\n'.join(f"| {r['candidate']} | {pct(r['precision'])} | {pct(r['recall'])} | {pct(r['f1'])} | {pct(r['false_positive_rate'])} |" for r in tradeoff),
        '## Fresh final anomaly comparison',table('anomaly_ml',('precision','recall','f1','false_positive_rate','mean_detection_delay_seconds','detected_fault_runs','total_fault_runs')),
        'Candidate warning quantile .985 instead of .99 retained all weights/features and the critical threshold. It failed the95% precision floor. More aggressive .98/.975/.95 validation candidates exceeded the1.5% false-positive bound. Active thresholds remain '+str(asdict(models['anomaly'].thresholds))+'.',
        'Combined-path recall increased only from '+pct(before['anomaly']['performance']['combined']['recall'])+' to '+pct(after['anomaly']['performance']['combined']['recall'])+'; its detected-only mean delay changed from215.33 to300 seconds. Newly detected late cases can worsen this conditional mean even when existing cases fire earlier. No active improvement is claimed.',
        '## Fresh final Stage B comparison',table('security',('nature_macro_f1','fault_vs_attack_macro_f1','origin_macro_f1','accepted_nature_accuracy','detector_coverage','normal_detector_fire','normal_nature_classifier_attack_label')),
        'Candidate nature minimum .54 instead of .58 retained calibrated weights, origin minimum .52 and margin .08. Accepted-prediction accuracy fell85.71% to83.33%, exceeding the1percentage-point loss guard. Attack precision fell89.66% to84.38%. It was rejected despite higher recall/F1. Active nature threshold remains .58; Undetermined/Unknown handling remains intact.',
        '## Source localization',table('source',('macro_f1','normal_precision','normal_recall','inverter_recall','sensor_recall','communication_recall','controller_recall','firmware_recall')),
        'No source candidate passed validation, so the final source comparison is the unchanged model on identical new runs. Leaf2/leaf1 macro-F1 were .90261/.90255 versus original .90295. The .60confidence/.10margin policy raised macro-F1 to.90724 but lowered Normal precision and barely improved inverter recall; guards required nondecreasing Normal precision and +1point inverter recall.',
        '## Difficult attack coverage (fresh regular final set)',
        '| Attack | Runs | Before detector fire | Candidate detector fire | Active after |\n|---|---:|---:|---:|---:|']
    for kind,r in before['security']['nature_recall_by_attack_type'].items():
        lines.append(f"| {kind} | {r['run_count']} | {pct(r['detector_fire_rate'])} | {pct(after['security']['nature_recall_by_attack_type'][kind]['detector_fire_rate'])} | {pct(r['detector_fire_rate'])} |")
    lines += ['Complete per-severity detection and attack-label rates are in final_before.json/final_after.json and comparison.csv. Groups are small (12runs per attack,4stealthy per attack in the dedicated test); no claim of statistical certainty is justified.',
        '## Dedicated stealth-excluded model',table('stealth',('nature_macro_f1','fault_vs_attack_macro_f1','origin_macro_f1','accepted_nature_accuracy','detector_coverage','normal_detector_fire')),
        'The dedicated artifact excluded the entire stealthy level during prior training. The active regular artifact did not; its fresh-seed/unseen-severity results must not be mislabeled as whole-level holdout. Dedicated-policy gains do not override failed regular acceptance. Its Normal detector fire rate is10% on this new set, an unresolved generalization weakness. Neither candidate changed origin predictions. See uncertainty.json for paired complete-run bootstrap bounds; ticks were not treated as independent.',
        '## Runtime and browser verification',
        'verify_accuracy_runtime.py uses the actual FastAPI lifespan, unchanged active model bundle and isolated in-memory persistence. Nine requested cases run through real injection,110ticks, inference, incidents and the agent. Normal produced zero alerts/incidents/jobs. Controller and sensor cases produced real automatic reports within480branch-ticks/threeattempts. Repeated status reads created no duplicates. Replay/message tampering were missed in this single moderate/seed42 scenario. Communication degradation had12combined alert ticks but no confirmed incident. These misses are recorded, not relabeled successes. Sensor fault was not forced into an attack classification. Live next_tick stayed110 during isolated agent work. All details/assessments are in runtime_verification.json.',
        'Browser observations are recorded separately; the nine injection cases used isolated application API checks, not nine manual browser demonstrations. The user live run and database were not reset by this study.',
        '## Files and artifacts',
        'New tracked-source candidates: scripts/optimize_accuracy.py, scripts/verify_accuracy_runtime.py, backend/tests/test_accuracy_optimization.py, docs/accuracy-optimization.md. Existing application, frontend, physics, agent, model-loading code and dependencies were not edited. Previous uncommitted Phase4 changes were preserved.',
        'All new research artifacts are under outputs/accuracy-optimization (Git-ignored). candidates/anomaly/anomaly.joblib is the rejected threshold candidate; candidates/security/selected.joblib is the rejected nature-policy candidate; candidates/source/source_classifier.joblib is a retained-original copy. accepted/ contains retained-original copies with explicit original-retained metadata, NOT newly approved models. Neither directory is an active configuration. Original hashes are recorded in original_manifest.json/acceptance.json.',
        'No activation or rollback is required. Existing scripts/run_reliable_api.ps1 and ORIGIN_* loading settings remain unchanged. Do not deploy the rejected candidates. Fresh-checkout prerequisites and reproduction commands are in docs/accuracy-optimization.md.',
        '## Remaining limitations',
        'No deployed accuracy gain was achieved. No new features, models, rules or inference thresholds were integrated. No external APIs, dependency upgrades, physics changes, ground-truth inference, agent-budget changes, commits or pushes occurred. Existing synthetic data may not represent real networks; weak observable effects and indistinguishable intent remain unresolved. Historical tests are development references, and this final set is now consumed and must not be reused for future tuning. Further feature/coverage work needs a separately predeclared study with a new untouched holdout, not a retest of these rejected settings.']
    if (ROOT/'verification.json').exists():
        checks=read(ROOT/'verification.json')
        lines += ['## Actual final regression and browser results',
            f"Backend: {checks['backend']['passed']} passed, {checks['backend']['failed']} failed, {checks['backend']['warnings']} existing warnings, {checks['backend']['seconds']}s. Frontend: {checks['frontend']['passed']} passed, {checks['frontend']['failed']} failed, {checks['frontend']['files']} files. TypeScript: {checks['typescript']}. Production build: {checks['production_build']}. Lint: {checks['lint']}.",
            checks['browser']+'. Screenshot: model-evaluation-browser.png. Browser checks did not reset the user run or change automatic-mode settings.']
    (ROOT/'REPORT.md').write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
    print('Wrote REPORT.md, comparison CSV/JSON, complete confusion matrices and grouped uncertainty',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=('reproduce','develop','final','report'))
    args=parser.parse_args();ROOT.mkdir(parents=True,exist_ok=True)
    models=load_models()
    {'reproduce':reproduce,'develop':develop,'final':final,'report':report_results}[args.phase](models)
