"""Reliability regressions using real simulator windows and preserved artifacts."""
from copy import deepcopy
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.api.config import ServerSettings
from app.api.models import ModelRegistry
from app.detection import AnomalyDetector, FeatureExtractor
from app.schemas.api import AttackRequest
from app.propagation.investigation import evidence_graph
from app.propagation.topology import build_topology
from app.security_analysis.dataset import AlertPolicy, SimulatedRun, live_incident_sample, observed_incident_windows
from app.security_analysis.features import FEATURE_NAMES, configured_features
from app.security_analysis.model import AbstentionPolicy, AttributionModels
from app.simulator import GridConfig, MicrogridSimulator

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "outputs/step5/original/held_out_fault_attack_origin.joblib"
CANDIDATE = ROOT / "outputs/step5/candidates/regular/selected.joblib"


@pytest.mark.parametrize("seed", [42, 73, 101])
def test_identical_observations_cannot_establish_inverter_fault_versus_attack(seed):
    fault, attack = MicrogridSimulator(seed=seed), MicrogridSimulator(seed=seed)
    fault.inject("inverter", "shutdown", severity=1, duration_ticks=120, start_tick=0)
    attack.inject_attack("actuator_abuse", "inverter", severity=1, duration_ticks=120, start_tick=0, stealth_level="naive")
    rows = fault.run(60)
    assert rows == attack.run(60)
    assert configured_features(rows[13:33], fault.config, baseline_rows=rows[:13]) == configured_features(attack.history[13:33], attack.config, baseline_rows=attack.history[:13])


def test_original_and_candidate_load_with_unchanged_thresholds_and_feature_schema():
    original = AttributionModels.load(ORIGINAL)
    candidate = AttributionModels.load(CANDIDATE)
    assert original.policy == candidate.policy == AbstentionPolicy()
    assert original.metadata["feature_names"] == candidate.metadata["feature_names"] == list(FEATURE_NAMES)
    assert candidate.metadata["origin_requires_determined_nature"] is False
    settings = ServerSettings(security_model=CANDIDATE, security_results_dir=CANDIDATE.parent)
    registry = ModelRegistry(settings)
    assert registry.security_analyzer is not None and registry.security_policy is not None


def test_independent_origin_acceptance_does_not_change_nature_or_raw_scores():
    original, candidate = AttributionModels.load(ORIGINAL), AttributionModels.load(CANDIDATE)
    sim = MicrogridSimulator(seed=42)
    sim.inject("inverter", "shutdown", severity=1, duration_ticks=120, start_tick=0)
    rows = sim.run(40)
    features = configured_features(rows[13:33], sim.config, baseline_rows=rows[:13])
    before, after = original.predict_features(features), candidate.predict_features(features)
    assert before["nature"] == after["nature"] == "Undetermined"
    assert before["origin"] == "Unknown"
    assert after["origin"] == "Actuator-Inverter"
    assert before["nature_candidates"] == after["nature_candidates"]
    assert before["origin_candidates"] == after["origin_candidates"]
    assert before["origin_abstention_reasons"] == ["Legacy artifact couples origin acceptance to nature acceptance"]
    assert after["origin_abstention_reasons"] == []
    assert after["nature_abstention_reasons"] and after["raw_origin_confidence"] > 0.9
    # Origin score/margin abstention must still function independently.
    cautious = deepcopy(candidate)
    cautious.policy = AbstentionPolicy(0.58, 0.9999, 0.9999)
    assert cautious.predict_features(features)["origin"] == "Unknown"


@pytest.mark.parametrize("efficiency", [0.95, 0.89])
def test_offline_live_window_features_and_timing_are_identical(workspace_tmp_path, monkeypatch, efficiency):
    settings = ServerSettings(database_path=workspace_tmp_path / "parity.sqlite3", security_model=CANDIDATE, security_results_dir=CANDIDATE.parent)
    with TestClient(create_app(settings)) as client:
        runtime = client.app.state.runtime
        config = {"solar_capacity_kw": 14, "battery_capacity_kwh": 30, "tick_seconds": 90, "discharge_efficiency": efficiency}
        assert client.post("/api/simulation/scenario", json={"seed": 42, "config": config}).status_code == 200
        features_seen = []
        real_predict = runtime.models.security_analyzer.predict_features
        def predict(features):
            assert tuple(features) == FEATURE_NAMES
            features_seen.append(deepcopy(features))
            return real_predict(features)
        monkeypatch.setattr(runtime.models.security_analyzer, "predict_features", predict)
        assert client.post("/api/simulation/inject-attack", json={"attack_type": "actuator_abuse", "target_component": "inverter", "duration_ticks": 120, "severity": 1, "stealth_level": "naive"}).status_code == 200
        assert client.post("/api/simulation/step", json={"ticks": 40}).status_code == 200
        packed = runtime.store.telemetry(runtime.run_id, -1, 100)
        rows = [item["telemetry"] for item in packed]
        run = SimulatedRun("offline-parity", 42, rows, "attack", "actuator_inverter", "actuator_abuse", None, "naive", 1, 0, 120, runtime.sim.config)
        sample = live_incident_sample(run, runtime.models.detector, runtime.models.security_policy, statuses=[item["anomaly"] for item in packed])
        assert sample is not None and sample["features"] in features_seen
        assessment = runtime.store.incidents(run_id=runtime.run_id)["items"][0]["security_attribution"]
        assert sample["detector_fire_tick"] == assessment["detector_fire_tick"]
        assert sample["inference_tick"] == assessment["inference_tick"]
        assert len(sample["telemetry_window"]) == 20
        assert sample["inference_tick"] < runtime.sim.tick


def test_shared_window_pipeline_rejects_hidden_labels_including_baseline():
    sim = MicrogridSimulator(seed=42)
    rows = sim.run(40)
    for field in ("attack_type", "fault_kind", "ground_truth", "injected_attack_target"):
        contaminated = deepcopy(rows[:13])
        contaminated[0][field] = "secret"
        with pytest.raises(ValueError, match="Hidden scenario field"):
            configured_features(rows[13:33], sim.config, baseline_rows=contaminated)


def test_live_sampling_never_truncates_at_hidden_event_end_or_uses_future_ticks():
    sim = MicrogridSimulator(seed=42)
    sim.inject("inverter", "shutdown", severity=1, start_tick=0, duration_ticks=15)
    rows = sim.run(40)
    detector = AnomalyDetector.load(ServerSettings().anomaly_model)
    policy = AlertPolicy(**json.loads((ORIGINAL.parent / "held_out_evaluation.json").read_text())["alert_policy"])
    run = SimulatedRun("short-event", 42, rows, "fault", "actuator_inverter", "inverter", "shutdown", None, 1, 0, 15, sim.config)
    sample = live_incident_sample(run, detector, policy)
    assert sample is not None and len(sample["telemetry_window"]) == 20
    assert sample["inference_tick"] >= 15
    statuses = detector.predict(FeatureExtractor(sim.config).transform(rows[:14]))
    assert observed_incident_windows(rows[:14], statuses, sim.config, policy) == []
    with pytest.raises(ValueError, match="same observed ticks"):
        observed_incident_windows(rows, statuses, sim.config, policy)


def test_model_selection_and_calibration_are_run_and_seed_disjoint():
    selection = json.loads((CANDIDATE.parent / "selection_before_test.json").read_text())
    splits = selection["splits"]
    for a, left in splits.items():
        for b, right in splits.items():
            if a != b:
                assert {item["run_id"] for item in left}.isdisjoint(item["run_id"] for item in right)
                assert {item["seed"] for item in left}.isdisjoint(item["seed"] for item in right)
    assert set(selection["extra_normal_training_seeds"]["fit"]).isdisjoint(selection["extra_normal_training_seeds"]["calibration"])
    all_test = {item["seed"] for item in splits["test"]}
    assert all_test.isdisjoint(selection["extra_normal_training_seeds"]["fit"] + selection["extra_normal_training_seeds"]["calibration"])
    assert selection["selected_using"] == "validation only; all thresholds unchanged"


def test_promoted_policy_meets_predeclared_regular_held_out_guards():
    comparison = json.loads((CANDIDATE.parent / "comparison.json").read_text())
    before, after = comparison["before"], comparison["after"]
    assert comparison["passes_frozen_test_guards"]
    assert after["nature_macro_f1"] == before["nature_macro_f1"]
    assert after["origin_macro_f1"] > before["origin_macro_f1"]
    assert after["origin"]["prediction_coverage_on_detected"] > before["origin"]["prediction_coverage_on_detected"]
    assert after["origin"]["accepted_accuracy"] >= before["origin"]["accepted_accuracy"]
    assert after["normal_false_attack_rate"] <= before["normal_false_attack_rate"]


def test_graph_respects_explicit_independent_origin_without_claiming_attack_intent():
    topology = build_topology()
    graph = {"nodes": [{"id": node} for node in topology],
             "edges": [{"source": a, "target": b} for a, b in topology.edges]}
    result = evidence_graph(graph, {"available": True, "nature_verdict": "Undetermined", "origin": "Actuator-Inverter",
        "origin_independent_of_nature": True}, [])
    assert result["security_candidate_nodes"] == ["inverter"]
    assert result["security_paths"] == []
    assert "none is confirmed compromised" in result["security_origin_message"]
    result = evidence_graph(graph, {"available": True, "nature_verdict": "Undetermined", "origin": "Unknown",
        "origin_independent_of_nature": True}, [])
    assert result["security_candidate_nodes"] == []


# Import after fixtures/constants to keep the actual app integration explicit.
from app.main import create_app
