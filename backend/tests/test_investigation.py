from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.detection import AnomalyDetector
from app.detection.dataset import normal_runs
from app.explainability.evidence import collect_evidence, describe, observable_sample
from app.explainability.incidents import IncidentTracker, investigate
from app.localization import LocalizationFeatureExtractor, SourceLocalizer
from app.localization.dataset import partition_runs
from app.propagation import build_topology
from app.propagation.investigation import incident_graph
from app.simulator import GridConfig, MicrogridSimulator


def rule_detection(row, checks=(), *, status=None):
    """Explicit unit-test model output, not measured ML performance."""
    return {"tick": row["tick"], "elapsed_seconds": row["elapsed_seconds"],
            "anomaly_score": 0.5 if status != "critical" else 0.9,
            "ml_status": "normal" if status != "critical" else "critical",
            "warning_threshold": 0.6, "critical_threshold": 0.8,
            "residual_checks": list(checks),
            "combined_status": status or ("warning" if checks else "normal")}


def inverter_stream(ticks=35, start=5, duration=15):
    sim = MicrogridSimulator(GridConfig(start_hour=16))
    sim.inject("inverter", "shutdown", start_tick=start, duration_ticks=duration)
    rows = sim.run(ticks)
    observations = LocalizationFeatureExtractor(sim.config).transform(rows)
    detections = [rule_detection(row, obs.evidence) for row, obs in zip(rows, observations)]
    return rows, detections


def test_confirmation_recovery_and_actual_numerical_explanation():
    rows, detections = inverter_stream()
    reports = investigate(rows, detections)
    assert len(reports) == 1
    report = reports[0]
    assert report["first_observed_tick"] == 5 and report["detection_tick"] == 7
    assert report["confirmation_delay_seconds"] == 120
    assert report["last_alert_tick"] == 19 and report["resolved_at_tick"] == 24
    assert report["status"] == "resolved"
    assert report["diagnosis"]["source"] == "unknown"
    assert not report["diagnosis"]["source_model_available"]
    text = " ".join(item["text"] for item in report["explanation"]["deviations"])
    assert "produces 0.000 kW" in text
    assert report["explanation"]["diagnostic_checks"]
    assert not any(edge["suspected"] for edge in report["graph"]["edges"])
    json.dumps(reports, allow_nan=False)


def test_isolated_warnings_do_not_open_incident_but_critical_does():
    rows, detections = inverter_stream()
    tracker = IncidentTracker()
    tracker.update(rows[0], rule_detection(rows[0], status="warning"))
    tracker.update(rows[1], rule_detection(rows[1]))
    assert tracker.reports() == []
    tracker.update(rows[2], rule_detection(rows[2], status="critical"))
    report = tracker.reports()[0]
    assert report["detection_tick"] == 2 and report["severity"] == "critical"
    assert "0.90000" in report["explanation"]["why_flagged"][0]


def test_neither_source_predictions_nor_resource_scarcity_open_incidents():
    sim = MicrogridSimulator(GridConfig(start_hour=0, initial_soc_pct=10))
    rows = sim.run(8)
    assert all(row["unmet_demand_kw"] > 0 for row in rows)
    assert investigate(rows, [rule_detection(row) for row in rows]) == []


def test_stream_snapshots_are_causal_copied_and_resettable():
    rows, detections = inverter_stream()
    tracker = IncidentTracker()
    for row, detection in zip(rows[:10], detections[:10]):
        tracker.update(row, detection)
    snapshot = tracker.reports()
    retained = deepcopy(snapshot)
    for row, detection in zip(rows[10:], detections[10:]):
        tracker.update(row, detection)
    assert snapshot == retained
    assert snapshot[0]["as_of_tick"] == 9
    assert all(item["tick"] <= 9 for item in snapshot[0]["evidence"])
    assert all(sample["tick"] <= 9 for node in snapshot[0]["graph"]["nodes"] for sample in node["telemetry"])
    snapshot[0]["samples"].clear()
    assert tracker.reports()[0]["samples"]
    tracker.reset()
    assert tracker.reports() == []
    for row, detection in zip(rows, detections):
        tracker.update(row, detection)
    assert tracker.reports()[0]["id"] == "incident-0001"


def test_ground_truth_and_hidden_oracles_do_not_enter_reports():
    rows, detections = inverter_stream()
    expected = investigate(rows, detections)
    changed = deepcopy(rows)
    for row in changed:
        row.update(fault="sensor", ground_truth="firmware", severity=1, actual_solar_kw=999,
                   battery_soc_pct=-500, battery_energy_kwh=999, nominal_command_kw=-999)
    assert investigate(changed, detections) == expected
    serialized = json.dumps(expected)
    assert "ground_truth" not in serialized and "actual_solar_kw" not in serialized


def test_structural_paths_each_reference_real_evidence_and_node_details():
    rows, detections = inverter_stream()
    sample = observable_sample(rows[8])
    evidence = collect_evidence(sample, detections[8], None)
    diagnosis = {"source": "inverter"}
    graph = incident_graph(diagnosis, evidence, [sample], [])
    topology = build_topology()
    assert graph["candidate_source_nodes"] == ["inverter"]
    assert "delivered" in graph["potentially_affected_nodes"]
    ids = {item["id"] for item in evidence}
    suspected = [edge for edge in graph["edges"] if edge["suspected"]]
    assert suspected
    for edge in graph["edges"]:
        assert topology.has_edge(edge["source"], edge["target"])
        if edge["suspected"]:
            assert set(edge["evidence_ids"]) <= ids and edge["evidence_ids"]
            assert "not directly established" in edge["uncertainty"]
    inverter = next(node for node in graph["nodes"] if node["id"] == "inverter")
    assert inverter["telemetry"][0]["inverter_actual_kw"] == 0
    assert all(not data["suspected"] for _, _, data in build_topology().edges(data=True))


def test_sensor_ambiguity_and_feedback_paths_are_finite():
    rows, detections = inverter_stream()
    sample = observable_sample(rows[8])
    evidence = collect_evidence(sample, detections[8], None)
    graph = incident_graph({"source": "sensor"}, evidence, [sample], [])
    assert graph["candidate_source_nodes"] == ["solar_sensor", "battery_sensor"]
    assert all(len(path["nodes"]) == len(set(path["nodes"])) for path in graph["suspected_paths"])


@pytest.mark.parametrize("mode", ["length", "time", "order", "nan"])
def test_validation_and_failed_updates_do_not_corrupt_state(mode):
    rows, detections = inverter_stream()
    tracker = IncidentTracker()
    tracker.update(rows[0], detections[0])
    with pytest.raises(ValueError):
        if mode == "length":
            investigate(rows, detections[:-1])
        elif mode == "time":
            tracker.update(rows[1], {**detections[1], "tick": 9})
        elif mode == "order":
            tracker.update(rows[2], detections[2])
        else:
            tracker.update(rows[1], {**detections[1], "anomaly_score": float("nan")})
    tracker.update(rows[1], detections[1])


@pytest.fixture(scope="module")
def models():
    detector = AnomalyDetector().fit(normal_runs("train", 4, 360), normal_runs("calibration", 3, 360))
    localizer = SourceLocalizer().fit(partition_runs("train", repeats=1, normal_count=8, ticks=240))
    return detector, localizer


def test_real_saved_model_cli_integration(models, workspace_tmp_path):
    detector, localizer = models
    detector.save(workspace_tmp_path / "anomaly.joblib")
    localizer.save(workspace_tmp_path / "source.joblib")
    root = Path(__file__).resolve().parents[2]
    output = workspace_tmp_path / "investigation"
    command = [sys.executable, "-m", "app.simulator", "--ticks", "100", "--fault", "inverter",
               "--mode", "shutdown", "--start", "20", "--duration", "60", "--correct-at", "60",
               "--anomaly-model", str(workspace_tmp_path / "anomaly.joblib"),
               "--source-model", str(workspace_tmp_path / "source.joblib"), "--investigate", "--output", str(output)]
    result = subprocess.run(command, cwd=root, env={**os.environ, "PYTHONPATH": str(root / "backend")},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    reports = json.loads((output / "incidents.json").read_text())
    principal = next(report for report in reports if any(item["signal"] == "inverter_output_residual" for item in report["evidence"]))
    predictions = json.loads((output / "source_predictions.json").read_text())
    representative = predictions[principal["representative_tick"]]
    expected = representative["predicted_source"]
    assert principal["diagnosis"]["source"] == ("unknown" if expected == "normal" else expected)
    assert principal["diagnosis"]["model_predicted_source"] == expected
    assert any(row["predicted_source"] == "inverter" for row in predictions[20:60])
    assert principal["status"] == "resolved"
    assert any(node["id"] == "inverter" and node["observed_symptom"] for node in principal["graph"]["nodes"])
    if principal["diagnosis"]["source"] == "unknown":
        assert not any(edge["suspected"] for edge in principal["graph"]["edges"])


def test_cli_requires_anomaly_model():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, "-m", "app.simulator", "--investigate"], cwd=root,
                            env={**os.environ, "PYTHONPATH": str(root / "backend")}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "requires --anomaly-model" in result.stderr


def test_separate_incidents_after_recovery_and_short_quiet_gap():
    rows = MicrogridSimulator().run(25)
    statuses = {tick: "warning" for tick in [*range(2, 6), *range(8, 11), *range(18, 22)]}
    reports = investigate(rows, [rule_detection(row, status=statuses.get(row["tick"], "normal")) for row in rows],
                          recovery_ticks=4)
    assert len(reports) == 2
    assert reports[0]["first_observed_tick"] == 2 and reports[0]["resolved_at_tick"] == 14
    assert reports[1]["id"] == "incident-0002" and reports[1]["status"] == "open"


def test_normal_classifier_conflict_remains_unknown_and_keeps_original_output():
    rows, detections = inverter_stream()
    sources = [{"tick": row["tick"], "elapsed_seconds": row["elapsed_seconds"],
                "predicted_source": "normal", "confidence": 0.9,
                "candidates": [{"source": "normal", "confidence": 0.9}, {"source": "sensor", "confidence": 0.1}],
                "abstention_reasons": [], "supporting_observations": []} for row in rows]
    report = investigate(rows, detections, sources)[0]
    assert report["diagnosis"]["source"] == "unknown"
    assert report["diagnosis"]["model_predicted_source"] == "normal"
    assert any("despite" in reason for reason in report["diagnosis"]["reasons"])
    assert report["explanation"]["alternative_sources"]


@pytest.mark.parametrize("kwargs", [{"confirmation_ticks": 0}, {"recovery_ticks": -1}, {"recovery_ticks": 1.5}])
def test_invalid_incident_windows(kwargs):
    with pytest.raises(ValueError):
        IncidentTracker(**kwargs)
