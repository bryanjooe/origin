from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import joblib
import numpy as np
import pytest

from app.detection.dataset import ScenarioRun, simulate_run, validate_partitions
from app.fault_injection import Fault
from app.localization import ConfidencePolicy, LocalizationFeatureExtractor, SourceLocalizer
from app.localization.dataset import CLASSES, UNKNOWN, partition_runs, selected_observations, supervised_table
from app.localization.evaluation import evaluate
from app.localization.features import FEATURE_NAMES


@pytest.fixture(scope="module")
def trained_source():
    runs = partition_runs("train", repeats=1, normal_count=8, ticks=240)
    return SourceLocalizer().fit(runs), runs


def test_scenario_partitions_and_training_targets(trained_source):
    model, runs = trained_source
    validation = partition_runs("validation", repeats=1, normal_count=2, ticks=240)
    validate_partitions(runs, validation)
    assert set(model.classifier.classes_) == set(CLASSES)
    table = supervised_table(runs)
    assert list(table.columns) == ["run_id", "tick", *FEATURE_NAMES, "target"]
    assert set(table["target"]) == set(CLASSES)
    assert "run_id" not in FEATURE_NAMES and "target" not in FEATURE_NAMES
    assert "severity" not in FEATURE_NAMES and "tick" not in FEATURE_NAMES
    with pytest.raises(ValueError, match="held out"):
        evaluate(model, runs)


def test_labels_oracles_and_future_never_change_features_or_predictions(trained_source):
    model, _ = trained_source
    run = simulate_run("leak-test", 901001, 80, Fault("sensor", "bias", 20, 40))
    expected = LocalizationFeatureExtractor(run.config).transform(run.telemetry)
    changed = deepcopy(run.telemetry)
    for row in changed:
        row.update(label="inverter", fault="controller", severity=999, ground_truth="communication",
                   actual_solar_kw=-900, battery_soc_pct=-500, battery_energy_kwh=-400,
                   nominal_command_kw=800, future_fault_source="firmware")
    actual = LocalizationFeatureExtractor(run.config).transform(changed)
    assert actual == expected
    assert model.predict(actual) == model.predict(expected)
    assert LocalizationFeatureExtractor(run.config).transform(run.telemetry[:30]) == expected[:30]
    # Altering target bookkeeping changes targets, never input vectors.
    relabeled = ScenarioRun(run.run_id, run.seed, run.config, run.telemetry, Fault("inverter", "derate", 20, 40))
    first, target = selected_observations(run)
    second, other_target = selected_observations(relabeled)
    assert target != other_target and first == second


def test_streaming_equivalence_and_soc_estimate():
    run = simulate_run("soc", 901002, 90, Fault("sensor", "soc_bias", 20, 40, 0.5))
    batch = LocalizationFeatureExtractor(run.config).transform(run.telemetry)
    extractor = LocalizationFeatureExtractor(run.config)
    assert [extractor.update(row) for row in run.telemetry] == batch
    assert batch[10].features["soc_level_residual_scaled"] == pytest.approx(0, abs=0.002)
    assert batch[30].features["soc_level_residual_scaled"] > 0.1
    assert batch[70].features["soc_level_residual_scaled"] == pytest.approx(0, abs=0.002)
    assert any(e["signal"] == "soc_energy_estimate_residual" for e in batch[30].evidence)
    midstream = LocalizationFeatureExtractor(run.config).transform(run.telemetry[10:20])
    assert all(obs.features["soc_estimate_available"] == 0 for obs in midstream)


def test_normal_and_clear_fault_predictions(trained_source):
    model, _ = trained_source
    for kind, mode in (("sensor", "bias"), ("communication", "corrupt"),
                       ("controller", "wrong_dispatch"), ("firmware", "discharge_limit"),
                       ("inverter", "shutdown")):
        run = simulate_run(f"predict-{kind}", 910000, 100, Fault(kind, mode, 20, 60, 1), start_hour=16)
        predictions = model.predict(LocalizationFeatureExtractor(run.config).transform(run.telemetry))
        assert any(result["predicted_source"] == kind for result in predictions[20:80]), kind
        result = predictions[40]
        assert sum(candidate["confidence"] for candidate in result["candidates"]) == pytest.approx(1)
        assert result["supporting_observations"]
        assert "not a proven root cause" in result["interpretation"]
    normal = simulate_run("normal-clear", 901003, 120, start_hour=10)
    predictions = model.predict(LocalizationFeatureExtractor(normal.config).transform(normal.telemetry))
    assert any(result["predicted_source"] == "normal" for result in predictions)


def test_unknown_on_low_confidence_and_ambiguity(trained_source):
    model, _ = trained_source
    observations = LocalizationFeatureExtractor(simulate_run("u", 99, 1).config).transform(simulate_run("u", 99, 1).telemetry)
    class AmbiguousClassifier:
        classes_ = np.asarray(CLASSES)
        def predict_proba(self, values):
            return np.tile([0.1, 0.42, 0.40, 0.03, 0.03, 0.02], (len(values), 1))
    ambiguous = SourceLocalizer()
    ambiguous.classifier = AmbiguousClassifier()
    result = ambiguous.predict(observations)[0]
    assert result["predicted_source"] == UNKNOWN
    assert result["confidence"] is None and len(result["abstention_reasons"]) == 2
    assert len(result["alternatives"]) == 2
    # Raising only the margin threshold also makes an otherwise confident tie abstain.
    assert ambiguous.predict(observations, ConfidencePolicy(0.3, 0.1))[0]["predicted_source"] == UNKNOWN
    assert ambiguous.predict(observations, ConfidencePolicy(0.3, 0.01))[0]["predicted_source"] == "sensor"
    run = simulate_run("midstream", 901007, 20)
    midstream = LocalizationFeatureExtractor(run.config).transform(run.telemetry[10:])
    assert all(result["predicted_source"] == UNKNOWN for result in model.predict(midstream))


def test_save_load_and_unavailable_models(trained_source, workspace_tmp_path):
    model, _ = trained_source
    path = workspace_tmp_path / "source.joblib"
    model.save(path)
    run = simulate_run("save", 901004, 30)
    observations = LocalizationFeatureExtractor(run.config).transform(run.telemetry)
    assert SourceLocalizer.load(path).predict(observations) == model.predict(observations)
    artifact = joblib.load(path)
    artifact["metadata"]["feature_version"] = -1
    joblib.dump(artifact, path)
    with pytest.raises(ValueError, match="mismatch"):
        SourceLocalizer.load(path)
    with pytest.raises(RuntimeError, match="unavailable"):
        SourceLocalizer().predict([])
    with pytest.raises(FileNotFoundError):
        SourceLocalizer.load(workspace_tmp_path / "missing.joblib")
    with pytest.raises(RuntimeError, match="untrained"):
        SourceLocalizer().save(path)


@pytest.mark.parametrize("confidence,margin", [(0, 0.1), (1.1, 0), (float("nan"), 0.1), (0.6, -1), (0.6, 1.1)])
def test_policy_validation(confidence, margin):
    with pytest.raises(ValueError):
        ConfidencePolicy(confidence, margin)


def test_missing_classes_and_invalid_scenarios():
    with pytest.raises(ValueError, match="all six"):
        SourceLocalizer().fit([simulate_run("only-normal", 901005, 30)])
    with pytest.raises(ValueError, match="required"):
        SourceLocalizer().fit([])
    with pytest.raises(ValueError):
        partition_runs("train", repeats=0)
    with pytest.raises(ValueError):
        partition_runs("train", ticks=10)


def test_heldout_metrics_include_unknowns(trained_source):
    model, runs = trained_source
    heldout = partition_runs("test", repeats=1, normal_count=2, ticks=240)
    report = evaluate(model, heldout)
    assert set(report["per_class"]) == set(CLASSES)
    assert report["raw_accuracy"] > 0.5
    assert report["accepted_accuracy"] > 0.65
    assert 0 <= report["unknown_rate"] <= 1
    assert report["accuracy_including_unknown"] <= report["coverage"]
    matrix = np.asarray(report["confusion_matrix"]["counts"])
    assert matrix.shape == (7, 7) and matrix.sum() == report["rows"]
    assert matrix[-1].sum() == 0  # Unknown is an abstention, not an injected source label.
    assert matrix[:, -1].sum() == round(report["unknown_rate"] * report["rows"])
    json.dumps(report, allow_nan=False)
    with pytest.raises(ValueError, match="disjoint"):
        evaluate(model, [heldout[0], heldout[0]])
    assert all(run.seed not in {item.seed for item in runs} for run in heldout)


def test_localization_cli_export(trained_source, workspace_tmp_path):
    model, _ = trained_source
    path = workspace_tmp_path / "source.joblib"
    model.save(path)
    output = workspace_tmp_path / "scored"
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(root / "backend")}
    command = [sys.executable, "-m", "app.simulator", "--ticks", "70", "--fault", "firmware",
               "--mode", "discharge_limit", "--start", "15", "--duration", "40", "--source-model", str(path),
               "--output", str(output)]
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    predictions = json.loads((output / "source_predictions.json").read_text())
    assert len(predictions) == 70
    assert any(row["predicted_source"] == "firmware" for row in predictions[15:55])
    telemetry = json.loads((output / "telemetry.json").read_text())
    assert all("predicted_source" not in row for row in telemetry)
    missing = subprocess.run([sys.executable, "-m", "app.simulator", "--source-model", str(path) + "missing"],
                             cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert missing.returncode == 2 and "Source model unavailable" in missing.stderr


def test_deterministic_training(trained_source):
    model, runs = trained_source
    repeated = SourceLocalizer().fit(runs)
    run = simulate_run("deterministic", 901006, 20)
    observations = LocalizationFeatureExtractor(run.config).transform(run.telemetry)
    assert repeated.predict(observations) == model.predict(observations)
