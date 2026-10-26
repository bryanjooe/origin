from copy import deepcopy

import pytest

from app.attack_injection import StealthLevel
from app.detection import AnomalyDetector
from app.detection.dataset import ScenarioRun
from app.security_analysis.attribution import build_attribution
from app.security_analysis.dataset import (AlertPolicy, _first_policy_fire,
    calibrate_alert_policy, generate_runs, split_runs)
from app.security_analysis.features import FEATURE_NAMES, extract_window
from app.security_analysis.evaluation import unalerted_run_output
from app.security_analysis.model import (
    AbstentionPolicy, AttributionModels, NATURE_CLASSES, ORIGIN_CLASSES,
)


def _samples():
    samples = []
    for i, nature in enumerate(NATURE_CLASSES):
        for j, origin in enumerate(ORIGIN_CLASSES if nature != "normal" else (None,)):
            features = {name: 0.001 * (i + j + k) for k, name in enumerate(FEATURE_NAMES)}
            samples.append({"run_id": f"fit-{i}-{j}", "seed": i * 10 + j,
                            "nature": nature, "origin_layer": origin,
                            "features": features, "telemetry_window": []})
    return samples


def test_dataset_generation_reproducible_and_window_causal():
    options = dict(repeats=1, ticks=210, seed=8801, severities=(0.7,),
                   stealth_levels=(StealthLevel.NAIVE,))
    first = generate_runs(**options)
    second = generate_runs(**options)
    assert [(run.run_id, run.seed, run.telemetry) for run in first] == [
        (run.run_id, run.seed, run.telemetry) for run in second]
    assert {run.scenario_type for run in first if run.nature == "attack"} == {
        "sensor_spoof", "replay", "communication_degradation", "message_tampering",
        "controller_compromise", "firmware_tampering", "actuator_abuse", "multi_stage"}
    rows = first[-1].telemetry
    inference_window = rows[20:40]
    assert extract_window(inference_window) == extract_window(rows[:40])


def test_feature_pipeline_rejects_hidden_engine_fields():
    run = generate_runs(repeats=1, ticks=200, seed=981, severities=(0.8,),
                        stealth_levels=("naive",))[0]
    contaminated = deepcopy(run.telemetry[:3])
    contaminated[1]["attack_engine_record"] = {"attack_type": "replay"}
    with pytest.raises(ValueError, match="Hidden scenario field"):
        extract_window(contaminated)
    contaminated = deepcopy(run.telemetry[:3])
    contaminated[1]["fault_mode"] = "bias"
    with pytest.raises(ValueError, match="Hidden scenario field"):
        extract_window(contaminated)


def test_splits_keep_complete_runs_and_seeds_disjoint():
    runs = generate_runs(repeats=2, ticks=200, seed=1181, severities=(0.7,),
                         stealth_levels=("naive", "moderate", "stealthy"))
    train, test = split_runs(runs, seed=7)
    assert {run.run_id for run in train}.isdisjoint(run.run_id for run in test)
    assert {run.seed for run in train}.isdisjoint(run.seed for run in test)
    train, test = split_runs(runs, seed=8, held_out_stealth="stealthy")
    assert all(run.stealth_level != "stealthy" for run in train)
    assert any(run.stealth_level == "stealthy" for run in test)
    assert {run.seed for run in train}.isdisjoint(run.seed for run in test)


def test_classifier_outputs_valid_labels_and_abstains():
    model = AttributionModels().fit(_samples(), seed=11)
    output = model.predict_features(_samples()[0]["features"])
    assert output["available"] is True
    assert output["nature"] in {"Normal", "Accidental fault", "Cyber attack", "Undetermined"}
    assert output["origin"] in {"Sensor", "Communication", "Controller", "Firmware-Config",
                                "Actuator-Inverter", "Unknown"}
    cautious = AttributionModels(AbstentionPolicy(0.99, 0.99, 0.99)).fit(_samples(), seed=11)
    output = cautious.predict_features(_samples()[0]["features"])
    assert output["nature"] == "Undetermined"
    assert output["origin"] == "Unknown"


def test_attribution_counts_match_source_telemetry():
    run = next(run for run in generate_runs(repeats=1, ticks=220, seed=1301,
        severities=(0.8,), stealth_levels=("naive",)) if run.nature == "attack"
        and run.scenario_type == "message_tampering")
    rows = run.telemetry[run.start_tick:run.start_tick + 20]
    invalid = sum(row["security_telemetry"]["auth_tag_validity"] == "invalid" for row in rows)
    attribution = build_attribution(rows, {"nature": "Cyber attack", "nature_confidence": 0.8,
        "origin_candidates": [{"layer": "Communication", "confidence": 0.7}]})
    observation = attribution["points_toward_attack"][0]
    assert observation["value"] == f"{invalid} of {len(rows)}"
    assert "indicators, not proof" in attribution["statement"]


def test_untrained_model_reports_unavailable_without_predictions():
    output = AttributionModels().predict_features({name: 0.0 for name in FEATURE_NAMES})
    assert output["available"] is False
    assert output["nature"] == "not available"
    assert output["nature_confidence"] is None
    assert output["origin"] == "not available"
    assert output["origin_candidates"] == []


def test_alert_gate_requires_warmup_and_persistence():
    policy = AlertPolicy(score_threshold=0.8, warmup_ticks=5, persistence_ticks=2)
    base = {"anomaly_score": 0.0, "residual_checks": []}
    statuses = [dict(base, tick=tick) for tick in range(8)]
    statuses[1]["anomaly_score"] = 1.0  # ignored during warm-up
    statuses[5]["anomaly_score"] = 1.0  # isolated spike does not fire
    statuses[6]["anomaly_score"] = 0.0
    statuses[7]["anomaly_score"] = 1.0
    assert _first_policy_fire(statuses, policy) is None
    statuses[6]["anomaly_score"] = 0.9
    assert _first_policy_fire(statuses, policy) == 5


def test_expanded_generator_oversamples_normals_for_balanced_nature_classes():
    runs = generate_runs(repeats=1, ticks=200, seed=19931, severities=(0.25, 0.6, 1.0),
                         stealth_levels=("naive", "moderate", "stealthy"))
    counts = {nature: sum(run.nature == nature for run in runs)
              for nature in ("normal", "fault", "attack")}
    assert counts == {"normal": 60, "fault": 48, "attack": 72}
    assert max(counts.values()) / min(counts.values()) == 1.5


def test_causal_cross_signal_features_include_pre_event_auth_baseline():
    run = generate_runs(repeats=1, ticks=220, seed=197, severities=(0.8,),
                        stealth_levels=("naive",))[0]
    rows = deepcopy(run.telemetry[10:30])
    baseline = deepcopy(run.telemetry[:10])
    baseline[0]["security_telemetry"]["auth_tag_validity"] = "invalid"
    actual = extract_window(rows, baseline_rows=baseline)
    assert actual["auth_invalid_rate_delta"] == pytest.approx(-0.1)
    assert actual["onset_step_ratio"] >= 0
    assert actual["persistent_signal_run"] >= 0
    assert actual["multi_signal_consistency_rate"] >= 0


def test_both_candidate_models_fit_and_sigmoid_calibration_is_run_disjoint():
    samples = _samples()
    validation = []
    for item in samples:
        copy = deepcopy(item)
        copy["run_id"] = "validation-" + copy["run_id"]
        copy["seed"] += 1000
        validation.append(copy)
    rf = AttributionModels().fit(samples, seed=13, algorithm="random_forest")
    gb = AttributionModels().fit(samples, seed=13, algorithm="gradient_boosting")
    calibrated = AttributionModels().fit(samples, seed=13, algorithm="random_forest",
                                         calibration_samples=validation)
    assert rf.metadata["algorithm"] == "random_forest"
    assert gb.metadata["algorithm"] == "gradient_boosting"
    assert calibrated.metadata["confidence_kind"] == "sigmoid_calibrated_probability"
    assert calibrated.metadata["calibration_run_ids"]
    with pytest.raises(ValueError, match="disjoint"):
        AttributionModels().fit(samples, seed=13, calibration_samples=samples)


def test_validation_alert_calibration_uses_run_level_fpr_constraint():
    # Small test uses the real seeded simulator and existing Stage 2 model artifact.
    # The split itself guarantees no training data is selected for calibration.
    runs = generate_runs(repeats=2, ticks=200, seed=1551, severities=(0.7,),
                         stealth_levels=("naive",))
    train, validation = split_runs(runs, test_fraction=0.5, seed=4)
    assert {run.seed for run in train}.isdisjoint(run.seed for run in validation)
    assert any(run.nature == "normal" for run in validation)
    assert any(run.nature != "normal" for run in validation)
    detector = AnomalyDetector().fit(
        [ScenarioRun(run.run_id, run.seed, run.config, run.telemetry)
         for run in train if run.nature == "normal"],
        [ScenarioRun(run.run_id, run.seed, run.config, run.telemetry)
         for run in validation if run.nature == "normal"], seed=31)
    policy, findings = calibrate_alert_policy(validation, detector)
    assert policy.warmup_ticks > 0
    assert "validation_normal_false_alert_rate" in findings
    assert "validation_event_coverage" in findings


def test_no_alert_run_is_scored_normal_and_origin_stays_unknown():
    result = unalerted_run_output()
    assert result["nature"] == "Normal"
    assert result["nature_confidence"] is None
    assert result["origin"] == "Unknown"
