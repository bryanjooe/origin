"""Real telemetry checks for missing data, causality, leakage and honest fusion."""
from copy import deepcopy

import pytest

from app.detection import AnomalyDetector, FeatureExtractor
from app.detection.security_signals import SecuritySidecar, SecuritySignalExtractor, SidecarFeatureExtractor, SIGNALS, persistent_fusion
from app.simulator import GridConfig, MicrogridSimulator


@pytest.fixture(scope='module')
def normal():
    config=GridConfig(start_hour=10)
    return config,MicrogridSimulator(config,73).run(720)


def test_prefix_invariance_and_incremental_batch_agreement(normal):
    config,rows=normal
    short=SecuritySignalExtractor(config).transform(rows[:32])
    long=SecuritySignalExtractor(config).transform(rows)
    assert short==long[:32]
    streaming=SecuritySignalExtractor(config)
    assert [streaming.update(r) for r in rows[:32]]==short


def test_injected_metadata_does_not_change_any_security_feature(normal):
    config,rows=normal
    altered=deepcopy(rows[:32])
    for row in altered:
        row.update(attack_type='replay',target_component='controller',ground_truth={'source':'sensor'},hidden_schedule=[0,20])
        row['security_telemetry']['evaluation_label']='attack'
    assert SecuritySignalExtractor(config).transform(altered)==SecuritySignalExtractor(config).transform(rows[:32])


def test_missing_and_nonfinite_security_data_is_unavailable_not_normal_or_bad(normal):
    config,rows=normal;missing=deepcopy(rows[:16])
    for row in missing:
        row.pop('security_telemetry',None);row.pop('redundant_solar_kw',None);row['redundant_soc_pct']=float('nan')
    sample=SecuritySignalExtractor(config).transform(missing)[-1]
    assert sample['counts']==dict.fromkeys(SIGNALS,0)
    model=SecuritySidecar();model.limits={n:.001 for n in SIGNALS}
    assert model.infer([sample])==[[]]


def test_missing_authentication_is_not_an_invalid_tag(normal):
    config,rows=normal;changed=deepcopy(rows[:16])
    for row in changed:row['security_telemetry']['auth_tag_validity']='missing'
    sample=SecuritySignalExtractor(config).transform(changed)[-1]
    assert sample['counts']['auth_invalid_rate']==0
    assert sample['counts']['solar_redundancy_gap']==8


def test_stale_reused_invalid_packet_is_not_eight_authentication_failures(normal):
    config,rows=normal;changed=deepcopy(rows[:16])
    for row in changed:
        row['security_telemetry']['auth_tag_validity']='invalid'
        row['controller_inputs']={'sequence_number':7}
    sample=SecuritySignalExtractor(config).transform(changed)[-1]
    assert sample['counts']['auth_invalid_rate']==1
    model=SecuritySidecar();model.limits={n:1 for n in SIGNALS}
    model.limits['auth_invalid_rate']=.25
    assert model.infer([sample])==[[]]


def test_delay_startup_does_not_manufacture_sequence_or_auth_evidence():
    config=GridConfig(communication_delay_ticks=5)
    rows=MicrogridSimulator(config,42).run(10)
    samples=SecuritySignalExtractor(config).transform(rows)
    assert all(s['counts']['auth_invalid_rate']==0 for s in samples[:5])
    assert all(s['values']['sequence_anomaly_rate']==0 for s in samples)


@pytest.mark.parametrize('method',['envelope','isolation_forest'])
def test_fusion_preserves_ml_scores_labels_thresholds_and_all_existing_alerts(normal,method):
    config,rows=normal
    signals=SecuritySignalExtractor(config).transform(rows)
    sidecar=SecuritySidecar(method).fit(signals[:400],signals[400:])
    sim=MicrogridSimulator(config,42)
    sim.inject_attack('replay','communication',severity=.8,duration_ticks=80,start_tick=20)
    testing=sim.run(120)
    baseline=AnomalyDetector.load('outputs/stage2/anomaly.joblib').predict(FeatureExtractor(config).transform(testing))
    original=deepcopy(baseline)
    fused=sidecar.fuse(baseline,SecuritySignalExtractor(config).transform(testing))
    assert baseline==original
    for b,a in zip(baseline,fused):
        assert all(b[key]==a[key] for key in ('anomaly_score','ml_status','warning_threshold','critical_threshold','ml_explanation'))
        assert b['combined_status']=='normal' or a['combined_status']==b['combined_status']
    if method=='isolation_forest':assert 'sequence_anomaly_rate' in sidecar.metadata['constant_features_excluded_from_if']


def test_optional_composition_preserves_the_original_feature_vector(normal):
    config,rows=normal
    original=FeatureExtractor(config).transform(rows[:32])
    augmented=SidecarFeatureExtractor(config).transform(rows[:32])
    assert [o.vector() for o in original]==[o.vector() for o in augmented]
    assert [o.features for o in original]==[o.features for o in augmented]
    assert [o.residual_checks for o in original]==[o.residual_checks for o in augmented]


def test_failed_base_telemetry_does_not_advance_optional_security_window(normal):
    config,rows=normal;extractor=SidecarFeatureExtractor(config)
    invalid={**rows[0],'measured_solar_kw':float('nan')}
    with pytest.raises(ValueError):extractor.update(invalid)
    assert extractor.security.previous_tick is None
    assert extractor.update(rows[0]).tick==0


def test_persistence_keeps_existing_residuals_and_critical_alerts_immediate(normal):
    config,rows=normal
    sim=MicrogridSimulator(config,42)
    sim.inject('controller','wrong_dispatch',severity=.8,duration_ticks=60,start_tick=10)
    testing=sim.run(80)
    baseline=AnomalyDetector.load('outputs/stage2/anomaly.joblib').predict(FeatureExtractor(config).transform(testing))
    fused=persistent_fusion(baseline,SecuritySignalExtractor(config).transform(testing))
    assert any(r['residual_checks'] for r in baseline)
    for before,after in zip(baseline,fused):
        assert before['ml_status']==after['ml_status'] and before['anomaly_score']==after['anomaly_score']
        if before['residual_checks'] or before['ml_status']=='critical':assert after['combined_status']!='normal'


def test_security_persistence_requires_repeated_observations_and_is_causal(normal):
    config,rows=normal;signals=SecuritySignalExtractor(config).transform(rows)
    model=SecuritySidecar().fit(signals[:400],signals[400:])
    sim=MicrogridSimulator(config,42)
    sim.inject_attack('replay','communication',severity=.8,start_tick=20,duration_ticks=60)
    testing=sim.run(100)
    baseline=AnomalyDetector.load('outputs/stage2/anomaly.joblib').predict(FeatureExtractor(config).transform(testing))
    samples=SecuritySignalExtractor(config).transform(testing)
    full=persistent_fusion(baseline,samples,model)
    assert full[:40]==persistent_fusion(baseline[:40],samples[:40],model)
    assert any(r['security_signal_findings'] for r in full[20:80])
    raw=model.infer(samples)
    for i,result in enumerate(full):
        for finding in result['security_signal_findings']:
            assert i>=2 and all(any(v['signal']==finding['signal'] for v in raw[j]) for j in range(i-2,i+1))


def test_alignment_errors_are_rejected_instead_of_fusing_unrelated_runs(normal):
    config,rows=normal
    baseline=AnomalyDetector.load('outputs/stage2/anomaly.joblib').predict(FeatureExtractor(config).transform(rows[:10]))
    samples=SecuritySignalExtractor(config).transform(rows[:10])
    with pytest.raises(ValueError):persistent_fusion(baseline,samples[1:])
    samples[5]['tick']=999
    with pytest.raises(ValueError):persistent_fusion(baseline,samples)
