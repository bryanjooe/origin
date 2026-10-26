import asyncio
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import json
import time

from fastapi.testclient import TestClient
import pytest

from app.api.config import ServerSettings
from app.api.runtime import SimulationRuntime
from app.database import Store
from app.detection import AnomalyDetector
from app.detection.dataset import normal_runs
from app.localization import SourceLocalizer
from app.localization.dataset import partition_runs
from app.main import create_app


@pytest.fixture
def client(workspace_tmp_path):
    settings = ServerSettings(database_path=workspace_tmp_path / "api.sqlite3", anomaly_model=None, source_model=None)
    with TestClient(create_app(settings)) as connection:
        yield connection


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_health_state_missing_models_and_schema(client):
    health = data(client.get("/api/health"))
    assert health["status"] == "degraded" and not health["models"]["anomaly"]["available"]
    state = data(client.get("/api/system/state"))
    assert state["next_tick"] == 0 and state["anomaly"] is None and state["telemetry"] is None
    assert client.get("/openapi.json").status_code == 200
    assert data(client.get("/api/system/topology"))["edges"]
    assert client.post("/api/model/evaluate").status_code == 503
    security = data(client.get("/api/security/metrics"))
    assert security["provenance"] == "synthetic simulations only"
    assert security["held_out"]["nature"]["count"] > 0
    assert set(security["class_run_counts"]) == {"normal", "fault", "attack"}
    state = data(client.post("/api/simulation/step", json={"ticks": 3}))
    assert state["next_tick"] == 3 and state["anomaly"] is None and state["source"] is None
    assert data(client.get("/api/incidents"))["total"] == 0


def test_security_incident_attribution_is_explicit_when_model_missing(client):
    runtime = client.app.state.runtime
    runtime.models.security_analyzer = None
    result = runtime.security_attribution({"run_id": "unused"})
    assert result["available"] is False
    assert result["nature_verdict"] == "Undetermined"
    assert result["nature_confidence"] is None
    assert result["origin"] == "Unknown"
    assert "not available" in result["reason"]


@pytest.mark.parametrize("path,body", [
    ("step", {"ticks": 0}), ("step", {"ticks": True}), ("step", {"ticks": 301}),
    ("speed", {"speed": 0}), ("start", {"unexpected": 1}),
    ("inject-fault", {"kind": "sensor", "mode": "shutdown"}),
    ("inject-fault", {"kind": "sensor", "mode": "bias", "severity": 1.1}),
    ("scenario", {"config": {"initial_soc_pct": 5, "reserve_soc_pct": 10}}),
    ("scenario", {"config": {"solar_capacity_kw": -1}}),
])
def test_api_request_validation(client, path, body):
    response = client.post(f"/api/simulation/{path}", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert data(client.get("/api/system/state"))["next_tick"] == 0


def test_deterministic_step_reset_pagination_and_historical_telemetry(client):
    initial = data(client.get("/api/system/state"))["run_id"]
    data(client.post("/api/simulation/step", json={"ticks": 10}))
    first = data(client.get("/api/telemetry", params={"limit": 4}))
    second = data(client.get("/api/telemetry", params={"after_tick": first["next_after_tick"], "limit": 20}))
    assert [item["telemetry"]["tick"] for item in first["items"] + second["items"]] == list(range(10))
    old = [item["telemetry"] for item in first["items"] + second["items"]]
    reset = data(client.post("/api/simulation/reset"))
    assert reset["run_id"] != initial and reset["next_tick"] == 0
    data(client.post("/api/simulation/step", json={"ticks": 10}))
    assert [item["telemetry"] for item in data(client.get("/api/telemetry"))["items"]] == old
    assert len(data(client.get("/api/telemetry", params={"run_id": initial}))["items"]) == 10
    scenarios = data(client.get("/api/scenarios"))
    assert len(scenarios) == 2
    assert all(item["metadata"]["next_tick"] == 10 for item in scenarios)


def test_schedule_overlap_past_validation_and_counterfactual_correction(client):
    scenario = {"seed": 42, "fault": {"kind": "inverter", "mode": "shutdown", "start_tick": 5, "duration_ticks": 50}}
    data(client.post("/api/simulation/scenario", json=scenario))
    assert client.post("/api/simulation/inject-fault", json={"kind": "sensor", "mode": "bias", "start_tick": 10}).status_code == 422
    data(client.post("/api/simulation/step", json={"ticks": 20}))
    assert client.post("/api/simulation/inject-fault", json={"kind": "sensor", "mode": "bias", "start_tick": 1}).status_code == 422
    before = data(client.get("/api/metrics/sustainability"))
    data(client.post("/api/simulation/correct"))
    data(client.post("/api/simulation/step", json={"ticks": 20}))
    after = data(client.get("/api/metrics/sustainability"))
    assert before["comparison"]["baseline"]["delivered_kwh"] > before["comparison"]["operated"]["delivered_kwh"]
    assert after["estimated_correction_delivery_gain_kwh"] > 0
    assert {item["ticks"] for item in after["comparison"].values()} == {40}
    assert all(abs(item["energy_balance_residual_kwh"]) < 1e-8 for item in after["comparison"].values())
    truth = data(client.get("/api/simulation/scenario"))["metadata"]["ground_truth"]
    assert truth["faults"][0]["cancelled_at_tick"] == 20
    assert "ground_truth" not in data(client.get("/api/system/state"))


def test_repeated_and_concurrent_start_pause_resume_one_worker(client):
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: client.post("/api/simulation/start", json={"speed": 10}), range(12)))
    assert all(response.status_code == 200 for response in results)
    time.sleep(0.12)
    paused = data(client.post("/api/simulation/pause"))
    tick = paused["next_tick"]
    assert tick > 0 and paused["worker_active"] and not paused["running"]
    worker = client.app.state.runtime.task
    time.sleep(0.12)
    assert data(client.get("/api/system/state"))["next_tick"] == tick
    data(client.post("/api/simulation/resume"))
    assert client.app.state.runtime.task is worker
    assert client.post("/api/simulation/reset").status_code == 409
    assert client.post("/api/simulation/step", json={"ticks": 1}).status_code == 409
    data(client.post("/api/simulation/pause"))
    telemetry = data(client.get("/api/telemetry"))["items"]
    ticks = [item["telemetry"]["tick"] for item in telemetry]
    assert ticks == list(range(len(ticks)))
    events = data(client.get("/api/events"))["items"]
    assert sum(event["event"] == "simulation_started" for event in events) == 2


def test_errors_exports_and_cors(client):
    assert client.get("/api/incidents/missing").status_code == 404
    assert client.get("/api/telemetry", params={"run_id": "missing"}).status_code == 404
    assert client.get("/api/telemetry", params={"limit": 999999}).status_code == 422
    data(client.post("/api/simulation/step", json={"ticks": 4}))
    response = client.get("/api/reports/export", params={"dataset": "telemetry", "format": "csv", "limit": 2})
    assert response.status_code == 200 and response.headers["x-export-truncated"] == "true"
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 2 and json.loads(rows[0]["telemetry"])["tick"] == 0
    exported = client.get("/api/reports/export", params={"dataset": "scenario"}).json()
    assert exported["data"][0]["metadata"]["ground_truth"]["label"]
    assert client.options("/api/system/state", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}).headers["access-control-allow-origin"] == "http://localhost:5173"


def test_failed_scenario_request_preserves_existing_run(client):
    initial = data(client.get("/api/system/state"))["run_id"]
    response = client.post("/api/simulation/scenario", json={"fault": {
        "kind": "sensor", "mode": "bias", "start_tick": 9999, "duration_ticks": 10}})
    assert response.status_code == 422
    assert data(client.get("/api/system/state"))["run_id"] == initial
    assert len(data(client.get("/api/scenarios"))) == 1


@pytest.fixture(scope="module")
def api_models():
    return (AnomalyDetector().fit(normal_runs("train", 4, 360), normal_runs("calibration", 3, 360)),
            SourceLocalizer().fit(partition_runs("train", repeats=1, normal_count=8, ticks=240)))


def test_real_models_incident_details_filters_graph_and_restart(api_models, workspace_tmp_path):
    detector, localizer = api_models
    detector.save(workspace_tmp_path / "anomaly.joblib")
    localizer.save(workspace_tmp_path / "source.joblib")
    settings = ServerSettings(database_path=workspace_tmp_path / "persistent.sqlite3",
                              anomaly_model=workspace_tmp_path / "anomaly.joblib", source_model=workspace_tmp_path / "source.joblib")
    with TestClient(create_app(settings)) as client:
        assert data(client.get("/api/health"))["status"] == "ok"
        data(client.post("/api/simulation/scenario", json={"fault": {"kind": "inverter", "mode": "shutdown", "start_tick": 10, "duration_ticks": 60}}))
        data(client.post("/api/simulation/step", json={"ticks": 35}))
        listing = data(client.get("/api/incidents"))
        assert listing["total"] > 0
        incident_id = listing["items"][0]["id"]
        report = data(client.get(f"/api/incidents/{incident_id}"))
        assert report["explanation"] and report["evidence"]
        assert report["created_at"].endswith("+00:00")
        assert data(client.get(f"/api/incidents/{incident_id}/graph"))["edges"]
        assert data(client.get("/api/incidents", params={"search": incident_id}))["total"] == 1
        assert data(client.get("/api/incidents", params={"source": report["diagnosis"]["source"]}))["total"] >= 1
        assert client.get("/api/reports/export", params={"dataset": "incidents", "format": "csv"}).status_code == 200
        old_run = report["run_id"]
        data(client.post("/api/simulation/reset"))
        archived = data(client.get(f"/api/incidents/{incident_id}"))
        assert archived["status"] == "interrupted" and archived["interruption_reason"] == "simulation_reset"
    with TestClient(create_app(settings)) as restarted:
        assert data(restarted.get(f"/api/incidents/{incident_id}"))["run_id"] == old_run
        assert len(data(restarted.get("/api/telemetry", params={"run_id": old_run}))["items"]) == 35


def test_evaluation_job_recomputes_and_persists_measured_results(api_models, workspace_tmp_path):
    detector, _ = api_models
    path = workspace_tmp_path / "anomaly.joblib"
    detector.save(path)
    settings = ServerSettings(database_path=workspace_tmp_path / "eval.sqlite3", anomaly_model=path, source_model=None)
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/model/evaluate", json={"profile": "quick"}).status_code == 202
        assert client.post("/api/model/evaluate", json={"profile": "quick"}).status_code == 409
        for _ in range(100):
            metrics = data(client.get("/api/model/metrics"))
            if metrics["evaluation"]["status"] != "running":
                break
            time.sleep(0.05)
        assert metrics["evaluation"]["status"] == "complete", metrics["evaluation"]
        report = metrics["reports"]["anomaly"]["report"]
        assert report["normal_rows"] == 360 and report["fault_rows"] == 600
        assert report["performance"]["ml"]["false_positive_rate"] is not None
    with TestClient(create_app(settings)) as restarted:
        assert data(restarted.get("/api/model/metrics"))["reports"]["anomaly"]["report"] == report


def test_tick_limit_and_shutdown_without_orphan_worker(workspace_tmp_path):
    async def run():
        service = SimulationRuntime(ServerSettings(database_path=workspace_tmp_path / "limit.sqlite3",
                                                   anomaly_model=None, source_model=None, max_ticks=2))
        await service.start(speed=30)
        for _ in range(100):
            if service.sim.tick == 2 and not service.running:
                break
            await asyncio.sleep(0.01)
        assert service.sim.tick == 2 and not service.running
        await service.close()
        assert service.task.done()
    asyncio.run(run())


def test_sqlite_crash_recovery_marks_open_history_interrupted(workspace_tmp_path):
    path = workspace_tmp_path / "crash.sqlite3"
    store = Store(path)
    store.create_scenario("run", {"seed": 42})
    store.update_scenario("run", "running", {"seed": 42})
    store.close()
    reopened = Store(path)
    reopened.recover_interrupted()
    assert reopened.scenario("run")["status"] == "interrupted"
    reopened.close()


def attack_body(**changes):
    return {"attack_type": "actuator_abuse", "target_component": "inverter",
            "severity": 1.0, "duration_ticks": 10, "stealth_level": "naive", **changes}


@pytest.mark.parametrize("kind,target", [
    ("sensor_spoof", "solar_sensor"), ("replay", "communication"),
    ("communication_degradation", "communication"), ("message_tampering", "communication"),
    ("controller_compromise", "controller"), ("firmware_tampering", "firmware"),
    ("actuator_abuse", "inverter"), ("multi_stage", "communication"),
])
def test_existing_attack_types_schedule_and_advance_via_api(client, kind, target):
    result = data(client.post("/api/simulation/inject-attack", json=attack_body(
        attack_type=kind, target_component=target, start_tick=2, duration_ticks=12)))
    assert result["scheduled"]["attack_type"] == kind
    state = data(client.post("/api/simulation/step", json={"ticks": 14}))
    assert state["next_tick"] == 14 and state["runtime_error"] is None
    runtime = client.app.state.runtime
    assert runtime.sim.history[:2] == runtime.baseline.history[:2]
    assert runtime.sim.history[2:] != runtime.baseline.history[2:]
    assert runtime.sim.history == runtime.uncorrected.history
    assert runtime.baseline.attacks.ground_truth() == []


@pytest.mark.parametrize("changes", [
    {"attack_type": "invalid"}, {"target_component": "controller"},
    {"target_component": "unknown"}, {"severity": 0}, {"severity": -0.1},
    {"severity": 1.1}, {"duration_ticks": 0}, {"duration_ticks": -1},
    {"duration_ticks": True}, {"duration_ticks": 1.5}, {"start_tick": -1},
    {"start_tick": True}, {"stealth_level": "invalid"}, {"unexpected": True},
])
def test_attack_request_validation_preserves_state(client, changes):
    runtime = client.app.state.runtime
    before = runtime.metadata()
    events = data(client.get("/api/events"))
    response = client.post("/api/simulation/inject-attack", json=attack_body(**changes))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert runtime.metadata() == before
    assert data(client.get("/api/events")) == events


def test_attack_schedule_past_overlap_limits_and_atomic_comparisons(client):
    runtime = client.app.state.runtime
    runtime.settings.max_ticks = 20
    data(client.post("/api/simulation/step", json={"ticks": 2}))
    for changes in ({"start_tick": 1}, {"start_tick": 19, "duration_ticks": 2}):
        before = runtime.metadata()
        assert client.post("/api/simulation/inject-attack", json=attack_body(**changes)).status_code == 422
        assert runtime.metadata() == before
    result = data(client.post("/api/simulation/inject-attack", json=attack_body()))
    assert result["scheduled"]["start_tick"] == 2
    assert "not a model prediction" in result["label"]
    data(client.post("/api/simulation/correct"))
    # The operated schedule is empty, but the counterfactual still conflicts.
    before = runtime.metadata()
    assert client.post("/api/simulation/inject-attack", json=attack_body(start_tick=5)).status_code == 422
    assert runtime.metadata() == before
    assert runtime.sim.attacks.at(5) is None
    data(client.post("/api/simulation/inject-attack", json=attack_body(start_tick=12, duration_ticks=8)))
    data(client.post("/api/simulation/step", json={"ticks": 18}))
    assert runtime.sim.tick == runtime.baseline.tick == runtime.uncorrected.tick == 20
    before = runtime.metadata()
    assert client.post("/api/simulation/inject-attack", json=attack_body()).status_code == 422
    assert runtime.metadata() == before


def test_attack_telemetry_correction_reset_and_ground_truth_separation(client, monkeypatch):
    runtime = client.app.state.runtime
    observed = []
    # Inspect the actual rows delivered to both existing inference extractors.
    for extractor in (runtime.extractor, runtime.source_extractor):
        original = extractor.update

        def capture(row, update=original):
            observed.append(row)
            return update(row)

        monkeypatch.setattr(extractor, "update", capture)
    data(client.post("/api/simulation/inject-attack", json=attack_body(start_tick=3)))
    data(client.post("/api/simulation/step", json={"ticks": 7}))
    assert runtime.sim.history[:3] == runtime.baseline.history[:3]
    assert runtime.sim.history == runtime.uncorrected.history
    assert runtime.sim.history[3]["inverter_actual_kw"] == 0
    assert runtime.baseline.history[3]["inverter_actual_kw"] > 0
    assert runtime.baseline.attacks.ground_truth() == []
    assert runtime.baseline.faults.ground_truth() == []
    assert len(observed) == 14
    forbidden = {"attack", "attack_type", "target_component", "stealth_level", "ground_truth"}

    def check_labels(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for child in value.values():
                check_labels(child)
        elif isinstance(value, list):
            for child in value:
                check_labels(child)

    check_labels(observed)
    check_labels(data(client.get("/api/system/state")))
    items = data(client.get("/api/telemetry"))["items"]
    check_labels(items)
    assert all(item["anomaly"] is None and item["source"] is None for item in items)
    assert data(client.get("/api/incidents"))["total"] == 0
    truth = data(client.get("/api/simulation/scenario"))["metadata"]["ground_truth"]
    assert truth["attacks"][0]["attack_type"] == "actuator_abuse"
    data(client.post("/api/simulation/correct"))
    data(client.post("/api/simulation/step", json={"ticks": 3}))
    assert runtime.sim.attacks.at(7) is None
    assert runtime.uncorrected.attacks.at(7) is not None
    assert runtime.sim.history[-1]["inverter_actual_kw"] > 0
    assert runtime.uncorrected.history[-1]["inverter_actual_kw"] == 0
    assert runtime.sim.attacks.ground_truth()[0]["cancelled_at_tick"] == 7
    metrics = data(client.get("/api/metrics/sustainability"))
    assert metrics["estimated_correction_delivery_gain_kwh"] > 0
    assert all(abs(item["energy_balance_residual_kwh"]) < 1e-8 for item in metrics["comparison"].values())
    old_run = runtime.run_id
    data(client.post("/api/simulation/reset"))
    assert all(sim.attacks.ground_truth() == [] for sim in (runtime.sim, runtime.baseline, runtime.uncorrected))
    archived = data(client.get("/api/scenarios"))
    assert next(item for item in archived if item["id"] == old_run)["metadata"]["ground_truth"]["attacks"]
    data(client.post("/api/simulation/inject-fault", json={"kind": "inverter", "mode": "shutdown"}))
    state = data(client.post("/api/simulation/step", json={"ticks": 2}))
    assert state["next_tick"] == 2 and state["telemetry"]["inverter_actual_kw"] == 0


def test_attack_injection_during_running_simulation_uses_existing_worker(client):
    data(client.post("/api/simulation/start", json={"speed": 30}))
    runtime = client.app.state.runtime
    worker = runtime.task
    result = data(client.post("/api/simulation/inject-attack", json=attack_body(start_tick=100)))
    paused = data(client.post("/api/simulation/pause"))
    assert paused["next_tick"] < 100
    assert result["scheduled"]["start_tick"] == 100
    assert runtime.task is worker
    data(client.post("/api/simulation/step", json={"ticks": 101 - paused["next_tick"]}))
    assert runtime.sim.history[100]["inverter_actual_kw"] == 0
    assert runtime.baseline.history[100]["inverter_actual_kw"] > 0
