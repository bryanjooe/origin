from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import joblib
import numpy as np
import pytest

from app.detection import AnomalyDetector, FeatureExtractor, Thresholds, FEATURE_NAMES
from app.detection.dataset import feature_table, normal_runs, simulate_run, validate_partitions
from app.detection.evaluation import binary_metrics, evaluate
from app.fault_injection import Fault


@pytest.fixture(scope="module")
def trained():
    train = normal_runs("train", 4, 360)
    calibration = normal_runs("calibration", 3, 360)
    return AnomalyDetector().fit(train, calibration), train, calibration


def test_normal_only_fit_and_complete_run_partitioning(trained):
    model, train, calibration = trained
    assert model.metadata["training_rows"] == 4 * 360
    assert model.metadata["calibration_rows"] == 3 * 360
    with pytest.raises(ValueError, match="disjoint"):
        model.fit(train, train)
    faulty = simulate_run("bad", 666, 360, Fault("sensor", "bias", 30))
    with pytest.raises(ValueError, match="normal-only"):
        model.fit([faulty], calibration)
    with pytest.raises(ValueError, match="disjoint"):
        validate_partitions(train, [simulate_run("other", train[0].seed, 5)])
    assert list(feature_table(train).columns) == ["run_id", "tick", *FEATURE_NAMES]


def test_no_label_or_oracle_leakage_and_no_future_lookahead():
    run = simulate_run("sample", 71, 20)
    expected = run.observations()
    altered = deepcopy(run.telemetry)
    for row in altered:
        row.update(fault="inverter", severity=1, kind="firmware", label="attack",
                   ground_truth={"source": "sensor"}, actual_solar_kw=999,
                   battery_soc_pct=-999, nominal_command_kw=999)
    got = FeatureExtractor(run.config).transform(altered)
    assert [row.features for row in got] == [row.features for row in expected]
    assert got[0].features.keys() == dict.fromkeys(FEATURE_NAMES).keys()
    prefix = FeatureExtractor(run.config).transform(run.telemetry[:10])
    assert prefix == expected[:10]
    changed_future = deepcopy(run.telemetry)
    changed_future[10]["measured_solar_kw"] += 100
    assert FeatureExtractor(run.config).transform(changed_future)[:10] == prefix


def test_online_and_batch_equivalence_and_reset():
    run = simulate_run("sample", 71, 40)
    batch = run.observations()
    online = FeatureExtractor(run.config)
    assert [online.update(row) for row in run.telemetry] == batch
    assert run.observations() == batch
    assert batch[0].features["soc_step_residual_z"] == 0


def test_bad_rows_rejected_without_mutating_stream():
    run = simulate_run("sample", 71, 5)
    extractor = FeatureExtractor(run.config)
    extractor.update(run.telemetry[0])
    bad = deepcopy(run.telemetry[1])
    bad["measured_solar_kw"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        extractor.update(bad)
    assert extractor.update(run.telemetry[1]) == run.observations()[1]
    with pytest.raises(ValueError, match="time-ordered"):
        extractor.update(run.telemetry[1])


def test_ml_and_rule_alerts_are_separate(trained):
    model, _, _ = trained
    run = simulate_run("bias", 55000, 360, Fault("sensor", "bias", 40, 160, 1), start_hour=10)
    results = model.predict(run.observations())
    assert np.median([r["anomaly_score"] for r in results[50:190]]) > np.median([r["anomaly_score"] for r in results[:30]])
    assert any(r["ml_status"] != "normal" for r in results[50:190])
    assert any(check["signal"] == "solar_measurement_residual" for check in results[50]["residual_checks"])
    assert results[50]["rule_status"] == "warning"
    assert "confidence" not in results[50] and "source" not in results[50]
    assert all(0 < r["anomaly_score"] < 1 for r in results)
    custom = model.predict(run.observations(), Thresholds(0.98, 0.99))
    assert custom[50]["ml_status"] == "normal"
    assert custom[50]["rule_status"] == "warning"
    assert custom[50]["combined_status"] == "warning"


def test_rule_checks_cover_constant_training_features(trained):
    model, _, _ = trained
    for kind, mode, expected_signal in [
        ("communication", "stale", "stale_telemetry"),
        ("firmware", "discharge_limit", "configuration_integrity"),
        ("controller", "wrong_dispatch", "controller_policy_residual"),
        ("inverter", "shutdown", "inverter_output_residual"),
    ]:
        run = simulate_run(f"{kind}-test", 56000, 100, Fault(kind, mode, 20, 60, 1), start_hour=16)
        results = model.predict(run.observations())
        assert any(c["signal"] == expected_signal for r in results[20:80] for c in r["residual_checks"])


def test_healthy_normal_false_positive_rate(trained):
    model, _, _ = trained
    runs = normal_runs("test", 4, 360)
    results = [result for run in runs for result in model.predict(run.observations())]
    assert sum(r["ml_status"] != "normal" for r in results) / len(results) < 0.1
    assert sum(r["rule_status"] != "normal" for r in results) / len(results) < 0.05


def test_save_load_and_version_guard(trained, workspace_tmp_path):
    model, _, _ = trained
    path = workspace_tmp_path / "anomaly.joblib"
    model.save(path)
    observations = simulate_run("save-test", 67, 30).observations()
    assert AnomalyDetector.load(path).predict(observations) == model.predict(observations)
    artifact = joblib.load(path)
    artifact["metadata"]["feature_version"] = -1
    joblib.dump(artifact, path)
    with pytest.raises(ValueError, match="mismatch"):
        AnomalyDetector.load(path)


def test_unavailable_model_and_threshold_validation(workspace_tmp_path):
    with pytest.raises(RuntimeError, match="unavailable"):
        AnomalyDetector().predict([])
    with pytest.raises(RuntimeError, match="untrained"):
        AnomalyDetector().save(workspace_tmp_path / "missing.joblib")
    with pytest.raises(FileNotFoundError):
        AnomalyDetector.load(workspace_tmp_path / "missing.joblib")
    for warning, critical in [(0.7, 0.6), (0, 0.6), (0.5, float("nan"))]:
        with pytest.raises(ValueError):
            Thresholds(warning, critical)


def test_real_metrics_and_held_out_guard(trained):
    model, train, _ = trained
    normal = normal_runs("test", 2, 360)
    faults = [simulate_run("heldout", 60000, 240, Fault("sensor", "bias", 40, 120, 1), start_hour=10)]
    report = evaluate(model, normal, faults)
    assert report["normal_rows"] == 720 and report["fault_rows"] == 120
    assert report["performance"]["combined"]["recall"] > 0.95
    assert report["performance"]["ml"]["roc_auc"] > 0.8
    json.dumps(report, allow_nan=False)
    with pytest.raises(ValueError, match="held out"):
        evaluate(model, train, faults)
    known = binary_metrics([False, False, True, True], [False, True, True, False])
    assert known["precision"] == known["recall"] == known["false_positive_rate"] == 0.5
    assert known["true_positive"] == known["false_positive"] == known["true_negative"] == known["false_negative"] == 1


def test_training_is_deterministic(trained):
    model, train, calibration = trained
    repeated = AnomalyDetector().fit(train, calibration)
    observations = simulate_run("replay", 19, 20).observations()
    assert model.predict(observations) == repeated.predict(observations)


def test_empty_training_bad_quantiles_and_small_dataset(trained):
    _, train, calibration = trained
    with pytest.raises(ValueError, match="normal-only"):
        AnomalyDetector().fit([], calibration)
    with pytest.raises(ValueError, match="quantile"):
        AnomalyDetector().fit(train, calibration, warning_quantile=0.999, critical_quantile=0.99)
    with pytest.raises(ValueError, match="at least"):
        AnomalyDetector().fit(normal_runs("train", 1, 20), normal_runs("calibration", 1, 20))


def test_unobservable_fault_and_missed_delay_are_not_fabricated(trained):
    model, _, _ = trained
    normal = normal_runs("test", 1, 30)
    # A stuck sensor holding an already zero night-time PV signal has no symptoms.
    run = simulate_run("night-stuck", 70000, 60, Fault("sensor", "stuck", 10, 30), start_hour=0)
    quiet_model = deepcopy(model)
    quiet_model.thresholds = Thresholds(0.98, 0.99)
    report = evaluate(quiet_model, normal, [run])
    record = report["per_run"][-1]
    assert record["combined_detection_delay_seconds"] is None
    assert report["performance"]["combined"]["detected_fault_runs"] == 0
    assert report["performance"]["combined"]["mean_detection_delay_seconds"] is None
    assert report["performance"]["combined"]["false_negative"] == 30


def test_simulator_cli_with_saved_detector(trained, workspace_tmp_path):
    model, _, _ = trained
    path = workspace_tmp_path / "model.joblib"
    model.save(path)
    root = Path(__file__).resolve().parents[2]
    output = workspace_tmp_path / "scored"
    result = subprocess.run([sys.executable, "-m", "app.simulator", "--ticks", "80",
                             "--fault", "sensor", "--mode", "bias", "--start", "20",
                             "--duration", "40", "--anomaly-model", str(path), "--output", str(output)],
                            cwd=root, env={**os.environ, "PYTHONPATH": str(root / "backend")},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    scores = json.loads((output / "anomaly_scores.json").read_text())
    events = json.loads((output / "anomaly_events.json").read_text())
    assert len(scores) == 80
    assert any(20 <= event["tick"] < 60 for event in events)
    assert all(event["combined_status"] != "normal" for event in events)
    assert all("elapsed_seconds" in event and "affected_variables" in event for event in events)
