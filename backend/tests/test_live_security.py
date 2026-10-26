"""Live integration checks against the existing, locally generated Stage B artifacts."""
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import joblib
import pytest

from app.api.config import ServerSettings
from app.api.models import ModelRegistry
from app.database import Store
from app.main import create_app
from app.security_analysis.features import FEATURE_NAMES, FEATURE_VERSION, extract_window


@pytest.fixture
def live(workspace_tmp_path):
    settings = ServerSettings(database_path=workspace_tmp_path / "live.sqlite3")
    with TestClient(create_app(settings)) as client:
        yield client, settings


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def inject(client, kind="attack"):
    if kind == "attack":
        return data(client.post("/api/simulation/inject-attack", json={
            "attack_type": "actuator_abuse", "target_component": "inverter",
            "severity": 1, "duration_ticks": 120, "stealth_level": "naive"}))
    return data(client.post("/api/simulation/inject-fault", json={
        "kind": "inverter", "mode": "shutdown", "severity": 1, "duration_ticks": 120}))


def reports(client):
    listing = data(client.get("/api/incidents"))
    return [data(client.get(f"/api/incidents/{item['id']}")) for item in listing["items"]]


def test_real_stage_b_models_and_policy_load_once(live, monkeypatch):
    client, _ = live
    runtime = client.app.state.runtime
    model = runtime.models.security_analyzer
    assert model is not None and runtime.models.security_policy is not None
    assert model.metadata["feature_version"] == FEATURE_VERSION
    assert model.metadata["feature_names"] == list(FEATURE_NAMES)
    assert runtime.models.fingerprints["security_attribution"]
    monkeypatch.setattr(type(model), "load", lambda *_: pytest.fail("Model reloaded during request"))
    inject(client)
    data(client.post("/api/simulation/step", json={"ticks": 40}))
    assert any(report["security_attribution"]["available"] for report in reports(client))


@pytest.mark.parametrize("scenario", ["fault", "attack"])
def test_real_predictions_observable_features_and_frozen_persisted_window(live, monkeypatch, scenario):
    client, _ = live
    runtime = client.app.state.runtime
    data(client.post("/api/simulation/scenario", json={"seed": 42,
        "config": {"solar_capacity_kw": 14, "battery_capacity_kwh": 30, "tick_seconds": 90,
                   "charge_efficiency": 0.91, "discharge_efficiency": 0.89}}))
    captured = []
    real_predict = runtime.models.security_analyzer.predict_features

    def predict(features):
        assert tuple(features) == FEATURE_NAMES
        captured.append(deepcopy(features))
        return real_predict(features)

    monkeypatch.setattr(runtime.models.security_analyzer, "predict_features", predict)
    # Any attempt to inspect hidden metadata in the inference path must fail.
    class HiddenTruth(dict):
        def get(self, *args):
            pytest.fail("Inference read hidden ground truth")
        def __getitem__(self, key):
            pytest.fail("Inference read hidden ground truth")
        def __iter__(self):
            pytest.fail("Inference iterated hidden ground truth")

    original_scenario = runtime.store.scenario
    def scenario_read(run_id):
        saved = original_scenario(run_id)
        if saved:
            saved["metadata"]["ground_truth"] = HiddenTruth()
        return saved
    monkeypatch.setattr(runtime.store, "scenario", scenario_read)
    inject(client, scenario)
    data(client.post("/api/simulation/step", json={"ticks": 40}))
    report = next(item for item in reports(client) if item["security_attribution"]["available"])
    assessment = report["security_attribution"]
    assert assessment["status"] == "available" and assessment["window_complete"]
    assert assessment["window_ticks"] == 20
    assert assessment["inference_tick"] < runtime.sim.tick
    rows = [item["telemetry"] for item in runtime.store.telemetry(runtime.run_id, -1, 100)]
    start = assessment["window_start_tick"]
    expected_features = extract_window(rows[start:start + 20], baseline_rows=rows[max(0, start - 20):start],
        solar_capacity_kw=14, battery_capacity_kwh=30, tick_seconds=90, communication_delay_ticks=0,
        charge_efficiency=0.91, discharge_efficiency=0.89)
    assert expected_features in captured
    prediction = real_predict(expected_features)
    for field, value in prediction.items():
        assert assessment[field] == value
    assert assessment["nature_verdict"] == prediction["nature"]
    if prediction["nature"] == "Undetermined":
        assert assessment["origin"] == "Unknown"
        assert assessment["origin_confidence"] is None
    assert all(item["window_ticks"] == 20 for item in assessment["evidence"]["ambiguous"])
    assert runtime.store.incident(report["id"])["security_attribution"] == assessment
    listing = data(client.get("/api/incidents"))["items"]
    assert next(item for item in listing if item["id"] == report["id"])["security_attribution"] == assessment
    count = len(captured)
    data(client.post("/api/simulation/step", json={"ticks": 8}))
    assert data(client.get(f"/api/incidents/{report['id']}"))["security_attribution"] == assessment
    assert len(captured) == count
    exported = client.get("/api/reports/export", params={"dataset": "incidents"}).json()["data"]
    assert next(item for item in exported if item["id"] == report["id"])["security_attribution"] == assessment


def test_pending_window_never_predicts_from_future_ticks(live, monkeypatch):
    client, _ = live
    runtime = client.app.state.runtime
    predictor = runtime.models.security_analyzer
    real_predict = predictor.predict_features
    calls = []
    monkeypatch.setattr(predictor, "predict_features", lambda features: (calls.append(features), real_predict(features))[1])
    inject(client)
    data(client.post("/api/simulation/step", json={"ticks": 14}))
    report = reports(client)[0]
    assessment = report["security_attribution"]
    assert assessment["status"] == "pending" and not assessment["available"]
    assert assessment["window_ticks"] < 20 and not calls
    assert assessment["window_end_tick"] <= 13
    target = assessment["detector_fire_tick"] + 20
    data(client.post("/api/simulation/step", json={"ticks": target - runtime.sim.tick}))
    assessment = data(client.get(f"/api/incidents/{report['id']}"))["security_attribution"]
    assert assessment["available"] and assessment["window_ticks"] == 20
    assert assessment["inference_tick"] == runtime.sim.tick - 1
    assert len(calls) == 1
    # A historical cutoff must not use later persisted rows, even on this same run.
    earlier = {**report, "id": "earlier-cutoff", "local_id": "earlier-cutoff", "as_of_tick": 13}
    earlier.pop("security_attribution")
    assert runtime.security_attribution(earlier)["status"] == "pending"
    assert len(calls) == 1


def test_assessment_history_survives_reset_and_restart_with_missing_models(live):
    client, settings = live
    runtime = client.app.state.runtime
    inject(client)
    data(client.post("/api/simulation/step", json={"ticks": 40}))
    report = next(item for item in reports(client) if item["security_attribution"]["available"])
    assessment = deepcopy(report["security_attribution"])
    data(client.post("/api/simulation/reset"))
    assert runtime.sim.tick == 0
    assert runtime.store.telemetry(runtime.run_id) == []
    assert runtime._security_cache == {} and runtime._security_waiting == {}
    assert data(client.get(f"/api/incidents/{report['id']}"))["security_attribution"] == assessment
    missing = ServerSettings(database_path=settings.database_path, security_model=None)
    with TestClient(create_app(missing)) as restarted:
        assert data(restarted.get(f"/api/incidents/{report['id']}"))["security_attribution"] == assessment


def test_reset_finalizes_incomplete_assessment_without_mixing_runs(live):
    client, _ = live
    inject(client)
    data(client.post("/api/simulation/step", json={"ticks": 14}))
    report = reports(client)[0]
    data(client.post("/api/simulation/reset"))
    saved = data(client.get(f"/api/incidents/{report['id']}"))["security_attribution"]
    assert saved["status"] == "insufficient_evidence" and not saved["available"]
    data(client.post("/api/simulation/step", json={"ticks": 40}))
    assert data(client.get(f"/api/incidents/{report['id']}"))["security_attribution"] == saved


def test_resolved_incident_receives_assessment_when_observed_window_finishes(live):
    client, _ = live
    inject(client)
    data(client.post("/api/simulation/step", json={"ticks": 14}))
    report = reports(client)[0]
    assert report["security_attribution"]["status"] == "pending"
    data(client.post("/api/simulation/correct"))
    data(client.post("/api/simulation/step", json={"ticks": 26}))
    saved = data(client.get(f"/api/incidents/{report['id']}"))
    assert saved["status"] == "resolved"
    assert saved["security_attribution"]["available"]
    assert saved["as_of_tick"] < saved["security_attribution"]["inference_tick"]
    assert saved["security_attribution"]["inference_tick"] < client.app.state.runtime.sim.tick


def test_legacy_report_is_enriched_once_without_replacing_diagnosis(live, monkeypatch):
    client, _ = live
    runtime = client.app.state.runtime
    inject(client)
    data(client.post("/api/simulation/step", json={"ticks": 40}))
    report = reports(client)[0]
    original = deepcopy(report)
    original.pop("created_at")
    original.pop("security_attribution")
    with runtime.store.connection:
        runtime.store.connection.execute("UPDATE incidents SET report=? WHERE id=?", (json.dumps(original), report["id"]))
    runtime._security_cache.clear()
    calls = []
    real_predict = runtime.models.security_analyzer.predict_features
    monkeypatch.setattr(runtime.models.security_analyzer, "predict_features", lambda features: (calls.append(features), real_predict(features))[1])
    for _ in range(3):
        enriched = data(client.get(f"/api/incidents/{report['id']}"))
        assert enriched["security_attribution"]["available"]
        assert enriched["diagnosis"] == original["diagnosis"]
    assert len(calls) == 1
    assert runtime.store.incident(report["id"])["security_attribution"] == enriched["security_attribution"]


@pytest.mark.parametrize("resolved", [False, True])
def test_crash_recovery_finalizes_pending_assessments(workspace_tmp_path, resolved):
    settings = ServerSettings(database_path=workspace_tmp_path / "crash.sqlite3")
    with TestClient(create_app(settings)) as client:
        inject(client)
        data(client.post("/api/simulation/step", json={"ticks": 14}))
        if resolved:
            data(client.post("/api/simulation/correct"))
            data(client.post("/api/simulation/step", json={"ticks": 8}))
        snapshot = reports(client)[0]
        assert snapshot["security_attribution"]["status"] == "pending"
        assert snapshot["status"] == ("resolved" if resolved else "open")
    # Restore the genuine durable snapshot from before graceful shutdown to
    # reproduce a process crash, including a resolved incident still collecting evidence.
    store = Store(settings.database_path)
    with store.connection:
        store.connection.execute("UPDATE incidents SET status=?,report=? WHERE id=?",
            (snapshot["status"], json.dumps(snapshot), snapshot["id"]))
    store.recover_interrupted()
    recovered = store.incident(snapshot["id"])
    assert recovered["security_attribution"]["status"] == "insufficient_evidence"
    assert not recovered["security_attribution"]["available"]
    assert recovered["status"] == ("resolved" if resolved else "interrupted")
    assert store.incidents()["items"][0]["status"] == recovered["status"]
    store.close()


@pytest.mark.parametrize("problem", ["missing", "feature_version", "feature_names", "sklearn_version", "missing_policy"])
def test_missing_and_incompatible_artifacts_preserve_simulation(workspace_tmp_path, problem):
    defaults = ServerSettings()
    model_path = workspace_tmp_path / "security.joblib"
    results_path = defaults.security_results_dir
    if problem in ("feature_version", "feature_names", "sklearn_version"):
        artifact = joblib.load(defaults.security_model)
        artifact["metadata"][problem] = -1 if problem == "feature_version" else [] if problem == "feature_names" else "incompatible"
        joblib.dump(artifact, model_path)
    elif problem == "missing_policy":
        model_path = defaults.security_model
        results_path = workspace_tmp_path
    settings = ServerSettings(database_path=workspace_tmp_path / "missing.sqlite3",
        security_model=model_path, security_results_dir=results_path)
    registry = ModelRegistry(settings)
    assert registry.security_analyzer is None and registry.security_error
    assert registry.detector is not None and registry.localizer is not None
    with TestClient(create_app(settings)) as client:
        inject(client)
        data(client.post("/api/simulation/step", json={"ticks": 14}))
        assessment = reports(client)[0]["security_attribution"]
        assert assessment["status"] == "unavailable" and not assessment["model_available"]
        assert assessment["nature_verdict"] == "Undetermined" and assessment["origin"] == "Unknown"
        assert assessment["reason"]
        data(client.post("/api/simulation/correct"))
        data(client.post("/api/simulation/inject-fault", json={"kind": "sensor", "mode": "bias"}))
        state = data(client.post("/api/simulation/step", json={"ticks": 2}))
        assert state["next_tick"] == 16 and state["runtime_error"] is None


def test_security_layer_does_not_change_phase1_diagnosis(workspace_tmp_path):
    diagnoses, telemetry = [], []
    for enabled in (True, False):
        settings = ServerSettings(database_path=workspace_tmp_path / f"phase1-{enabled}.sqlite3")
        if not enabled:
            settings.security_model = None
        with TestClient(create_app(settings)) as client:
            inject(client, "fault")
            data(client.post("/api/simulation/step", json={"ticks": 40}))
            diagnoses.append([report["diagnosis"] for report in reports(client)])
            telemetry.append(data(client.get("/api/telemetry"))["items"])
    assert diagnoses[0] == diagnoses[1]
    assert telemetry[0] == telemetry[1]
