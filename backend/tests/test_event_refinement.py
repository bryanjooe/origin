"""Final experimental-policy safety, causality and evidence-contract checks."""
from copy import deepcopy

import joblib
import pytest

from app.detection import AnomalyDetector, FeatureExtractor
from app.detection.dataset import normal_runs
from app.detection.event_refinement import onset_fusion
from app.detection.security_signals import SecuritySignalExtractor
from app.simulator import GridConfig, MicrogridSimulator


@pytest.fixture(scope='module')
def sidecar():return joblib.load('outputs/security-detector-study-v1/envelope999.joblib')


def observed(config,rows):
    baseline=AnomalyDetector.load('outputs/stage2/anomaly.joblib').predict(FeatureExtractor(config).transform(rows))
    return baseline,SecuritySignalExtractor(config).transform(rows)


@pytest.mark.parametrize('quorum',[2,3])
def test_real_isolated_warning_onset_is_not_removed_by_persistence(sidecar,quorum):
    run=normal_runs('test',1)[0];base,samples=observed(run.config,run.telemetry)
    result=onset_fusion(base,samples,sidecar,security_quorum=quorum)
    assert any(r['ml_status']=='warning' for r in base)
    pulses=[r['tick'] for r in result if r['weak_ml_onset_pulse']]
    assert pulses and all(b-a>=3 for a,b in zip(pulses,pulses[1:]))
    first=next(i for i,r in enumerate(base) if r['ml_status']=='warning' and not r['residual_checks'])
    assert result[first]['combined_status']=='warning' and result[first]['weak_ml_onset_pulse']


@pytest.mark.parametrize('quorum',[2,3])
def test_scores_physical_evidence_and_immediate_critical_alerts_are_unchanged(sidecar,quorum):
    config=GridConfig(start_hour=17,communication_delay_ticks=3)
    sim=MicrogridSimulator(config,42);sim.inject('controller','wrong_dispatch',severity=.8,start_tick=10,duration_ticks=60)
    base,samples=observed(config,sim.run(90));saved=deepcopy(base)
    result=onset_fusion(base,samples,sidecar,security_quorum=quorum)
    assert saved==base
    assert any(r['residual_checks'] for r in base)
    for b,a in zip(base,result):
        for key in ('anomaly_score','ml_status','warning_threshold','critical_threshold','ml_explanation','residual_checks','rule_status'):
            assert a[key]==b[key]
        if b['residual_checks'] or b['ml_status']=='critical':assert a['combined_status']!='normal'
    assert any(r['security_signal_findings'] for r in result) is False  # Controller evidence is original physical evidence.


@pytest.mark.parametrize('quorum',[2,3])
def test_real_security_evidence_is_separate_and_fusion_has_no_future_dependence(sidecar,quorum):
    config=GridConfig(start_hour=10)
    sim=MicrogridSimulator(config,42);sim.inject_attack('replay','communication',severity=.8,start_tick=20,duration_ticks=80)
    base,samples=observed(config,sim.run(120));original=deepcopy(samples)
    result=onset_fusion(base,samples,sidecar,security_quorum=quorum)
    assert result[:70]==onset_fusion(base[:70],samples[:70],sidecar,security_quorum=quorum)
    assert original==samples
    assert any(r['security_signal_findings'] for r in result[20:100])
    assert all(a['residual_checks']==b['residual_checks'] for a,b in zip(result,base))


def test_missing_domain_evidence_does_not_become_a_confirmed_finding(sidecar):
    config=GridConfig();rows=MicrogridSimulator(config,42).run(20)
    base,samples=observed(config,rows)
    for s in samples:s['counts']={name:0 for name in s['counts']}
    assert all(not r['security_signal_findings'] for r in onset_fusion(base,samples,sidecar))


def test_alignment_and_undeclared_policy_are_rejected(sidecar):
    config=GridConfig();base,samples=observed(config,MicrogridSimulator(config,42).run(10))
    with pytest.raises(ValueError):onset_fusion(base,samples,sidecar,security_quorum=1)
    with pytest.raises(ValueError):onset_fusion(base,samples[1:],sidecar)
    samples[4]['tick']=999
    with pytest.raises(ValueError):onset_fusion(base,samples,sidecar)
