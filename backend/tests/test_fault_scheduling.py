"""Scheduling regressions; no ML training or new scheduling policy."""
from fastapi.testclient import TestClient
import pytest

from app.api.config import ServerSettings
from app.main import create_app


@pytest.fixture
def client():
    settings = ServerSettings(database_path=":memory:", anomaly_model=None, source_model=None, security_model=None)
    with TestClient(create_app(settings)) as connection:
        yield connection


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


FAULT = {"kind": "inverter", "mode": "shutdown", "severity": 1, "duration_ticks": 5}


@pytest.mark.parametrize("tick", [0, 3, 180])
def test_next_tick_fault_on_fresh_or_paused_advanced_run(client, tick):
    if tick:
        data(client.post("/api/simulation/step", json={"ticks": tick}))
    result = data(client.post("/api/simulation/inject-fault", json=FAULT))
    assert result["scheduled"]["start_tick"] == tick
    runtime = client.app.state.runtime
    assert runtime.sim.faults.ground_truth() == runtime.uncorrected.faults.ground_truth()
    assert runtime.baseline.faults.ground_truth() == []
    data(client.post("/api/simulation/step", json={"ticks": 1}))
    assert runtime.sim.history[-1]["inverter_actual_kw"] == 0
    assert runtime.uncorrected.history[-1]["inverter_actual_kw"] == 0
    assert runtime.baseline.history[-1]["inverter_actual_kw"] > 0


def test_running_future_fault_and_atomic_next_tick(client):
    data(client.post("/api/simulation/start", json={"speed": 0.1}))
    first = data(client.post("/api/simulation/inject-fault", json=FAULT))
    assert first["scheduled"]["start_tick"] >= 0
    future = data(client.post("/api/simulation/inject-fault", json={**FAULT, "start_tick": 100}))
    assert future["scheduled"]["start_tick"] == 100
    paused = data(client.post("/api/simulation/pause"))
    assert not paused["running"]


def test_completed_fault_allows_new_nonoverlapping_fault(client):
    data(client.post("/api/simulation/inject-fault", json=FAULT))
    data(client.post("/api/simulation/step", json={"ticks": 5}))
    assert data(client.post("/api/simulation/inject-fault", json=FAULT))["scheduled"]["start_tick"] == 5


def test_correction_preserves_uncorrected_overlap_and_allows_later_fault(client):
    data(client.post("/api/simulation/inject-fault", json=FAULT))
    data(client.post("/api/simulation/step", json={"ticks": 2}))
    data(client.post("/api/simulation/correct"))
    runtime = client.app.state.runtime
    schedules = (runtime.sim.faults.ground_truth(), runtime.uncorrected.faults.ground_truth())
    rejected = client.post("/api/simulation/inject-fault", json=FAULT)
    assert rejected.status_code == 422
    assert "uncorrected comparison run" in rejected.json()["error"]["message"]
    assert schedules == (runtime.sim.faults.ground_truth(), runtime.uncorrected.faults.ground_truth())
    data(client.post("/api/simulation/inject-fault", json={**FAULT, "start_tick": 5}))
    data(client.post("/api/simulation/step", json={"ticks": 5}))
    metrics = data(client.get("/api/metrics/sustainability"))
    assert {ledger["ticks"] for ledger in metrics["comparison"].values()} == {7}
    assert all(abs(ledger["energy_balance_residual_kwh"]) < 1e-8 for ledger in metrics["comparison"].values())


def test_start_preplans_fault_and_genuine_duplicate_is_rejected(client):
    data(client.post("/api/simulation/scenario", json={"fault": {**FAULT, "start_tick": 30}}))
    runtime = client.app.state.runtime
    schedules = (runtime.sim.faults.ground_truth(), runtime.uncorrected.faults.ground_truth())
    rejected = client.post("/api/simulation/inject-fault", json={**FAULT, "start_tick": 30})
    assert rejected.status_code == 422
    assert "overlaps" in rejected.json()["error"]["message"]
    assert schedules == (runtime.sim.faults.ground_truth(), runtime.uncorrected.faults.ground_truth())


def test_cancelled_future_fault_still_reserves_uncorrected_interval(client):
    data(client.post("/api/simulation/inject-fault", json={**FAULT, "start_tick": 10}))
    data(client.post("/api/simulation/correct"))
    runtime = client.app.state.runtime
    assert runtime.sim.faults.ground_truth()[0]["cancelled_at_tick"] == 0
    assert runtime.uncorrected.faults.ground_truth()[0]["cancelled_at_tick"] is None
    # A disjoint earlier interval is valid, while the retained future interval is not.
    data(client.post("/api/simulation/inject-fault", json=FAULT))
    rejected = client.post("/api/simulation/inject-fault", json={**FAULT, "start_tick": 10})
    assert rejected.status_code == 422
    assert "uncorrected comparison run" in rejected.json()["error"]["message"]


def test_explicit_past_and_over_limit_faults_still_rejected(client):
    data(client.post("/api/simulation/step", json={"ticks": 40}))
    past = client.post("/api/simulation/inject-fault", json={**FAULT, "start_tick": 30})
    assert past.status_code == 422
    assert "past" in past.json()["error"]["message"]
    limit = client.post("/api/simulation/inject-fault", json={**FAULT, "start_tick": 9999})
    assert limit.status_code == 422
    assert "tick limit" in limit.json()["error"]["message"]
    assert client.app.state.runtime.sim.faults.ground_truth() == []


def test_reset_clears_new_schedules_but_preserves_history_and_attack_injection(client):
    initial = data(client.get("/api/system/state"))["run_id"]
    data(client.post("/api/simulation/inject-fault", json=FAULT))
    data(client.post("/api/simulation/step", json={"ticks": 2}))
    fresh = data(client.post("/api/simulation/reset"))
    assert fresh["next_tick"] == 0 and fresh["run_id"] != initial
    assert client.app.state.runtime.sim.faults.ground_truth() == []
    assert len(data(client.get("/api/telemetry", params={"run_id": initial}))["items"]) == 2
    data(client.post("/api/simulation/inject-fault", json=FAULT))
    attack = {"attack_type": "replay", "target_component": "communication", "duration_ticks": 5}
    assert data(client.post("/api/simulation/inject-attack", json=attack))["scheduled"]["start_tick"] == 0
    assert client.post("/api/simulation/inject-attack", json=attack).status_code == 422
    runtime = client.app.state.runtime
    assert runtime.sim.attacks.ground_truth() == runtime.uncorrected.attacks.ground_truth()
    assert runtime.baseline.attacks.ground_truth() == []
