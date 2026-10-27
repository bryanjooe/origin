"""Acceptance-policy regressions: better headline scores cannot bypass safeguards."""
from copy import deepcopy
import importlib.util
from pathlib import Path


spec=importlib.util.spec_from_file_location('accuracy_experiment',Path(__file__).resolve().parents[2]/'scripts/optimize_accuracy.py')
experiment=importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


def test_detector_recall_gain_cannot_override_precision_or_false_alert_limits():
    before={'performance':{'ml':{'f1':.45,'recall':.30,'precision':.98,'false_positive_rate':.008,
            'detected_fault_runs':69,'mean_detection_delay_seconds':600}}}
    candidate=deepcopy(before)
    candidate['performance']['ml'].update(f1=.55,recall=.4,precision=.94,detected_fault_runs=72)
    assert not experiment.anomaly_ok(before,candidate)
    candidate['performance']['ml'].update(precision=.96,false_positive_rate=.025)
    assert not experiment.anomaly_ok(before,candidate)
    candidate['performance']['ml'].update(false_positive_rate=.012)
    assert experiment.anomaly_ok(before,candidate)


def test_source_macro_gain_cannot_hide_weak_or_strong_class_regression():
    before={'macro_f1':.88,'accepted_accuracy':.95,'per_class':{c:{'precision':.9,'recall':.9} for c in
            ('normal','sensor','communication','controller','firmware','inverter')}}
    after=deepcopy(before);after['macro_f1']=.90;after['per_class']['inverter']['recall']=.92
    assert experiment.source_ok(before,after)
    after['per_class']['normal']['precision']=.89
    assert not experiment.source_ok(before,after)
    after['per_class']['normal']['precision']=.9;after['per_class']['firmware']['recall']=.88
    assert not experiment.source_ok(before,after)


def test_nature_macro_gain_cannot_hide_accepted_prediction_errors():
    before={'nature':{'macro_f1':.5},'fault_vs_attack':{'macro_f1':.4},'origin':{'macro_f1':.7},
        'normal_run_false_positive_rate':{'nature_classifier_attack_label':0},
        'row_level_results':[{'inference_tick':30,'nature_prediction':'Cyber attack','nature_truth':'attack'} for _ in range(10)]}
    after=deepcopy(before);after['nature']['macro_f1']=.52
    assert experiment.security_ok(before,after)
    after['row_level_results'][0]['nature_prediction']='Accidental fault'
    assert not experiment.security_ok(before,after)
