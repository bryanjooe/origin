"""Deterministic cloning, observable comparisons and live runtime isolation."""
import asyncio
from copy import deepcopy
from dataclasses import asdict, replace
import json
import pickle

import pytest

from app.api.config import ServerSettings
from app.api.runtime import SimulationRuntime
from app.schemas.api import AttackRequest, FaultRequest
from app.shadowtwin import ComparisonFrame, SimulationSnapshot
from app.simulator import GridConfig, MicrogridSimulator
from app.sustainability import EnergyLedger


RNG_NAMES = ("_weather", "_measurement", "_communication", "_redundant_measurement", "_attack_random", "_security_random")


def assert_observation(actual, raw):
    # Compare every existing raw field, not just the new structure's selected metrics.
    assert {key: actual[key] for key in raw} == raw
    assert actual["grid_import_kw"] is None and actual["grid_export_kw"] is None


def test_identical_initial_conditions_and_comparison_frames():
    first = MicrogridSimulator(seed=19)
    second = MicrogridSimulator(seed=19)
    left = SimulationSnapshot(first).fork("left")
    right = SimulationSnapshot(second).fork("right")
    for a, b in zip(left.advance(80), right.advance(80)):
        assert a == b
        frame = ComparisonFrame.from_rows("experiment-1", {"left": a, "right": b})
        assert frame.branch_ids == ("left", "right")
        assert frame.tick == a["tick"]
    assert first.tick == second.tick == 0


@pytest.mark.parametrize("scenario", ["normal", "stuck", "noise", "replay", "degradation", "firmware", "multi_stage", "inverter_delay"])
def test_intermediate_checkpoint_preserves_all_streams_and_subsequent_telemetry(scenario):
    source = MicrogridSimulator(GridConfig(start_hour=17, communication_delay_ticks=4, packet_loss_probability=0.15), seed=37)
    if scenario in ("stuck", "noise"):
        source.inject("sensor", scenario, start_tick=7, duration_ticks=180)
    elif scenario == "inverter_delay":
        source.inject("inverter", "delay", start_tick=7, duration_ticks=180)
    elif scenario != "normal":
        kind, target = {"replay": ("replay", "communication"),
                        "degradation": ("communication_degradation", "communication"),
                        "firmware": ("firmware_tampering", "firmware"),
                        "multi_stage": ("multi_stage", "communication")}[scenario]
        source.inject_attack(kind, target, stealth_level="stealthy", start_tick=7, duration_ticks=180)
    # A pending future schedule must also survive an intermediate checkpoint.
    source.inject_attack("replay", "communication", start_tick=210, duration_ticks=10)
    source.run(100)
    checkpoint = SimulationSnapshot(source)
    branch = checkpoint.fork("copy")
    assert branch.next_tick == checkpoint.next_tick == 100
    assert branch._simulator.config == source.config and branch._simulator.config is not source.config
    for name in RNG_NAMES:
        assert getattr(branch._simulator, name) is not getattr(source, name)
        assert getattr(branch._simulator, name).getstate() == getattr(source, name).getstate()
    expected = source.run(130)
    actual = branch.advance(130)
    for observed, raw in zip(actual, expected):
        assert_observation(observed, raw)
    for name in RNG_NAMES:
        assert getattr(branch._simulator, name).getstate() == getattr(source, name).getstate()
    assert branch._simulator.events == source.events
    assert branch._simulator.faults.ground_truth() == source.faults.ground_truth()
    assert branch._simulator.attacks.ground_truth() == source.attacks.ground_truth()
    # Reusing a checkpoint after the source advances still reproduces tick 100.
    assert checkpoint.fork("later-copy").advance(130) == actual


def test_mutable_state_queues_history_and_schedules_are_not_shared():
    source = MicrogridSimulator(GridConfig(communication_delay_ticks=4), seed=11)
    source.run(10)
    checkpoint = SimulationSnapshot(source)
    left, right = checkpoint.fork("left"), checkpoint.fork("right")
    original = pickle.dumps(source)
    sibling = pickle.dumps(right._simulator)
    left._simulator.battery_kwh -= 1
    left._simulator.config = replace(left._simulator.config, discharge_limit_kw=1)
    left._simulator._pending[0][1]["solar_kw"] = -99
    left._simulator.history[-1]["security_telemetry"]["config_integrity_match"] = False
    left._simulator.inject("sensor", "bias", duration_ticks=3)
    left._simulator.inject_attack("replay", "communication", duration_ticks=3)
    left._simulator._weather.random()
    assert pickle.dumps(source) == original
    assert pickle.dumps(right._simulator) == sibling
    assert checkpoint.fork("fresh").advance(3) == right.advance(3)


def test_weather_and_demand_remain_matched_with_branch_local_sensor_noise():
    checkpoint = SimulationSnapshot(MicrogridSimulator(seed=71))
    left, right = checkpoint.fork("left"), checkpoint.fork("right")
    # Existing fault engine only, to test isolation; no hypothesis selection logic.
    left._simulator.inject("sensor", "noise", severity=0.8, duration_ticks=50)
    a, b = left.advance(50), right.advance(50)
    assert [row["irradiance"] for row in a] == [row["irradiance"] for row in b]
    assert [row["demand_kw"] for row in a] == [row["demand_kw"] for row in b]
    assert [row["measured_solar_kw"] for row in a] != [row["measured_solar_kw"] for row in b]


def test_existing_ledger_is_copied_or_reconstructed_without_new_energy_math():
    sim = MicrogridSimulator(GridConfig(start_hour=18), seed=5)
    ledger = EnergyLedger(sim.config)
    for row in sim.run(50):
        ledger.update(row)
    copied = SimulationSnapshot(sim, ledger=ledger).fork("copied")
    reconstructed = SimulationSnapshot(sim).fork("reconstructed")
    before = deepcopy(ledger.snapshot())
    assert copied.energy_snapshot() == reconstructed.energy_snapshot() == before
    assert copied.advance(50) == reconstructed.advance(50)
    assert ledger.snapshot() == before
    for branch in (copied, reconstructed):
        result = branch.energy_snapshot()
        assert result["ticks"] == 100
        assert result["battery_energy_kwh"] == pytest.approx(branch._simulator.battery_kwh)
        assert abs(result["energy_balance_residual_kwh"]) < 1e-8
        assert abs(result["renewable_energy_balance_residual_kwh"]) < 1e-8
    altered = copied.energy_snapshot()
    altered["delivered_kwh"] = -1
    assert copied.energy_snapshot()["delivered_kwh"] >= 0


def test_reset_and_correction_do_not_change_existing_checkpoints():
    source = MicrogridSimulator(seed=7)
    source.inject("sensor", "stuck", duration_ticks=30)
    source.inject_attack("replay", "communication", duration_ticks=30)
    source.run(10)
    checkpoint = SimulationSnapshot(source)
    left = checkpoint.fork("left")
    expected = checkpoint.fork("right").advance(20)
    source.correct()
    source.reset(seed=999)
    assert left.advance(20) == expected
    assert source.tick == 0 and source.history == []


def test_comparison_data_filters_labels_recursively_without_exposing_checkpoint_state():
    source = MicrogridSimulator()
    source.inject_attack("replay", "communication", duration_ticks=20)
    raw = source.step()
    raw.update(ground_truth={"origin": "secret-target"}, attack_type="replay", faults=["secret-label"], engine_record={})
    raw["controller_inputs"]["true_origin"] = "secret-target"
    raw["security_telemetry"]["ground_truth"] = {"attack_type": "secret-label"}
    # Direct construction is as safe as the convenience factory.
    frame = ComparisonFrame("experiment-2", 0, {"a": raw, "b": raw})
    encoded = json.dumps(asdict(frame))
    assert all(token not in encoded for token in ("ground_truth", "attack_type", "faults", "engine_record", "true_origin", "secret-"))
    assert frame.telemetry["a"]["security_telemetry"]["config_hash"] == raw["security_telemetry"]["config_hash"]
    frame.telemetry["a"]["controller_inputs"]["solar_kw"] = -1
    assert raw["controller_inputs"]["solar_kw"] >= 0
    assert frame.telemetry["b"]["controller_inputs"]["solar_kw"] >= 0


@pytest.mark.parametrize("change", [{"tick": 1}, {"elapsed_seconds": 60}])
def test_comparison_rejects_misaligned_ticks_or_times(change):
    row = MicrogridSimulator().step()
    with pytest.raises(ValueError, match="matching"):
        ComparisonFrame.from_rows("experiment", {"a": row, "b": {**row, **change}})


def test_comparison_rejects_hidden_containers_in_numeric_measurements():
    row = MicrogridSimulator().step()
    with pytest.raises(ValueError, match="numeric"):
        ComparisonFrame.from_rows("experiment", {"a": row, "b": {**row, "demand_kw": {"ground_truth": "attack"}}})


@pytest.mark.parametrize("ticks", [True, -1, 1.5, 1001])
def test_invalid_or_excessive_advances_leave_state_unchanged(ticks):
    branch = SimulationSnapshot(MicrogridSimulator()).fork("bounded")
    before = pickle.dumps((branch._simulator, branch._ledger))
    with pytest.raises(ValueError):
        branch.advance(ticks)
    assert pickle.dumps((branch._simulator, branch._ledger)) == before


@pytest.mark.parametrize("limit", [True, 0, 10001])
def test_invalid_experiment_horizons_rejected(limit):
    with pytest.raises(ValueError, match="max_tick"):
        SimulationSnapshot(MicrogridSimulator(), max_tick=limit)


def test_absolute_limit_applies_across_multiple_advances():
    source = MicrogridSimulator()
    source.run(5)
    branch = SimulationSnapshot(source, max_tick=7).fork("bounded")
    with pytest.raises(ValueError, match="limit"):
        branch.advance(3)
    assert branch.next_tick == 5
    assert len(branch.advance(2)) == 2
    assert branch.advance(0) == []
    with pytest.raises(ValueError, match="limit"):
        branch.advance(1)
    assert branch.next_tick == 7


def test_missing_history_or_mismatched_ledger_is_not_silently_reconstructed():
    source = MicrogridSimulator()
    source.run(3)
    with pytest.raises(ValueError, match="ledger"):
        SimulationSnapshot(source, ledger=EnergyLedger(source.config))
    source.history.pop()
    with pytest.raises(ValueError, match="history"):
        SimulationSnapshot(source)


@pytest.mark.parametrize("requested", [9, 11, True, 10.0])
def test_requested_capture_tick_is_exact_or_rejected_without_time_travel(requested):
    source = MicrogridSimulator()
    source.run(10)
    before = pickle.dumps(source)
    with pytest.raises(ValueError, match="current state"):
        SimulationSnapshot(source, at_tick=requested)
    assert pickle.dumps(source) == before
    assert SimulationSnapshot(source, at_tick=10).next_tick == 10


@pytest.mark.parametrize("name", ["operated", "baseline", "faulty_uncorrected"])
def test_runtime_branch_capture_has_no_live_state_ledger_or_database_side_effects(name):
    async def scenario():
        runtime = SimulationRuntime(ServerSettings(database_path=":memory:", anomaly_model=None, source_model=None, security_model=None, max_ticks=30))
        try:
            await runtime.inject(FaultRequest(kind="sensor", mode="bias", duration_ticks=8))
            await runtime.inject_attack(AttackRequest(attack_type="replay", target_component="communication", duration_ticks=8))
            await runtime.step(3)
            await runtime.correct()
            before = pickle.dumps((runtime.sim, runtime.baseline, runtime.uncorrected, runtime.ledgers))
            state = deepcopy(runtime.state())
            database = list(runtime.store.connection.iterdump())
            checkpoint = await runtime.shadow_snapshot(name)
            branch = checkpoint.fork("experiment-copy")
            assert branch.next_tick == 3
            assert not hasattr(branch, "store") and not hasattr(branch, "models")
            branch.advance(10)
            assert runtime.state() == state
            assert pickle.dumps((runtime.sim, runtime.baseline, runtime.uncorrected, runtime.ledgers)) == before
            assert list(runtime.store.connection.iterdump()) == database
            engine = {"operated": runtime.sim, "baseline": runtime.baseline, "faulty_uncorrected": runtime.uncorrected}[name]
            expected = deepcopy(engine).step()
            assert_observation(checkpoint.fork("reference").advance(1)[0], expected)
            # Existing reset/history behavior and a previously forked experiment coexist.
            await runtime.reset(seed=999)
            assert runtime.sim.tick == 0 and branch.next_tick == 13
            assert branch.advance(1)[0]["tick"] == 13
            with pytest.raises(ValueError, match="limit"):
                branch.advance(17)
        finally:
            await runtime.close()
    asyncio.run(scenario())


def test_live_snapshot_waits_for_the_existing_runtime_lock():
    async def scenario():
        runtime = SimulationRuntime(ServerSettings(database_path=":memory:", anomaly_model=None, source_model=None, security_model=None))
        try:
            async with runtime.lock:
                pending = asyncio.create_task(runtime.shadow_snapshot())
                await asyncio.sleep(0)
                assert not pending.done()
                runtime._advance()
            checkpoint = await pending
            assert checkpoint.next_tick == runtime.sim.tick == 1
            with pytest.raises(ValueError, match="current state"):
                await runtime.shadow_snapshot(at_tick=0)
            assert (await runtime.shadow_snapshot(at_tick=1)).next_tick == 1
            with pytest.raises(ValueError, match="Choose"):
                await runtime.shadow_snapshot("not-a-branch")
        finally:
            await runtime.close()
    asyncio.run(scenario())
