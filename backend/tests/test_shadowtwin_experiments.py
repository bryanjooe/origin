"""Actual branch interventions, including neutral, wrong and temporary outcomes."""
import asyncio
from dataclasses import asdict
import json
import pickle

import pytest

from app.api.config import ServerSettings
from app.api.runtime import SimulationRuntime
from app.attack_injection import AttackEngine
from app.fault_injection import FaultEngine
from app.schemas.api import AttackRequest, FaultRequest
from app.shadowtwin import Hypothesis, ShadowBranch, SimulationSnapshot, run_experiment
from app.simulator import GridConfig, MicrogridSimulator


def hypothesis(intervention="use_redundant_solar", component="solar_sensor", **kwargs):
    return Hypothesis("H1", component, "caller-suspected behavior", intervention, **kwargs)


def source(kind="sensor_fault"):
    sim = MicrogridSimulator(GridConfig(start_hour=17, communication_delay_ticks=3), seed=42)
    if kind == "sensor_fault":
        sim.inject("sensor", "bias", severity=0.8, start_tick=0, duration_ticks=80)
    elif kind == "sensor_attack":
        sim.inject_attack("sensor_spoof", "solar_sensor", severity=0.8, stealth_level="naive", start_tick=0, duration_ticks=80)
    elif kind == "controller_attack":
        sim.inject_attack("controller_compromise", "controller", severity=0.8, start_tick=0, duration_ticks=80)
    elif kind == "replay":
        sim.inject_attack("replay", "communication", start_tick=5, duration_ticks=80)
    elif kind == "inverter_fault":
        sim.inject("inverter", "shutdown", start_tick=0, duration_ticks=80)
    sim.run(10)
    return sim


def test_no_intervention_has_identical_controls_and_zero_measured_differences():
    checkpoint = SimulationSnapshot(source())
    result = run_experiment(checkpoint, hypothesis("none"), experiment_id="no-op")
    assert result.status == "completed" and result.execution_tick is None
    assert result.control_telemetry == result.experimental_telemetry
    assert result.external_conditions_matched and result.random_states_matched
    assert all(row["experimental_minus_control"]["delivered_kw"] == 0 for row in result.observable_differences)


@pytest.mark.parametrize("kind", ["sensor_fault", "sensor_attack"])
def test_sensor_routing_changes_real_controller_inputs_and_physical_outputs(kind):
    sim = source(kind)
    checkpoint = SimulationSnapshot(sim)
    unchanged = checkpoint.fork("reference").advance(20)
    result = run_experiment(checkpoint, hypothesis(duration_ticks=20), experiment_id=kind)
    assert result.control_telemetry == unchanged
    assert result.status == "completed" and result.sustained
    assert (result.start_tick, result.end_tick, result.execution_tick) == (10, 30, 10)
    assert all(row["measured_solar_kw"] == row["redundant_solar_kw"] for row in result.experimental_telemetry)
    assert any(row["measured_solar_kw"] != row["redundant_solar_kw"] for row in result.control_telemetry)
    assert any(a["controller_inputs"]["solar_kw"] != b["controller_inputs"]["solar_kw"]
               for a, b in zip(result.control_telemetry[4:], result.experimental_telemetry[4:]))
    assert any(a["battery_energy_kwh"] != b["battery_energy_kwh"] for a, b in zip(result.control_telemetry, result.experimental_telemetry))
    assert result.external_conditions_matched and result.random_states_matched
    assert sim.tick == 10


def test_controller_override_uses_existing_nominal_policy_before_physics():
    result = run_experiment(SimulationSnapshot(source("controller_attack")),
        hypothesis("restore_controller_policy", "controller", duration_ticks=20), experiment_id="controller")
    assert result.status == "completed" and result.sustained
    assert all(row["controller_command_kw"] == row["nominal_command_kw"] for row in result.experimental_telemetry)
    assert any(row["controller_command_kw"] != row["nominal_command_kw"] for row in result.control_telemetry)
    assert any(a["battery_energy_kwh"] != b["battery_energy_kwh"] for a, b in zip(result.control_telemetry, result.experimental_telemetry))


def test_communication_flush_is_real_but_temporary_and_does_not_stop_replay():
    checkpoint = SimulationSnapshot(source("replay"))
    result = run_experiment(checkpoint, hypothesis("flush_communication", "communication", duration_ticks=20), experiment_id="flush")
    assert result.status == "completed" and not result.sustained
    assert result.intervention_status == "applied_once" and result.execution_tick == 10
    assert result.experimental_telemetry[0]["controller_inputs"] is None
    assert result.control_telemetry[0]["controller_inputs"] is not None
    assert result.experimental_telemetry[-1]["message_age_seconds"] > 0
    assert any("Ongoing manipulation remains active" in warning for warning in result.warnings)


def test_different_hypotheses_share_the_original_snapshot_without_assuming_a_winner():
    checkpoint = SimulationSnapshot(source("controller_attack"))
    sensor = run_experiment(checkpoint, hypothesis(duration_ticks=20), experiment_id="sensor")
    controller = run_experiment(checkpoint, hypothesis("restore_controller_policy", "controller", duration_ticks=20), experiment_id="controller")
    assert sensor.control_telemetry == controller.control_telemetry
    assert sensor.experimental_telemetry != controller.experimental_telemetry
    assert checkpoint.next_tick == 10
    assert all(not hasattr(controller, key) for key in ("winner", "rank", "resolved", "confidence", "proven_source"))


def test_wrong_hypothesis_does_not_restore_a_shutdown_inverter():
    result = run_experiment(SimulationSnapshot(source("inverter_fault")),
        hypothesis("restore_controller_policy", "controller", duration_ticks=20), experiment_id="wrong")
    assert result.status == "completed"  # Execution completed, not "problem resolved".
    assert result.control_telemetry == result.experimental_telemetry
    assert all(row["inverter_actual_kw"] == 0 for row in result.experimental_telemetry)
    assert result.energy["experimental_minus_control"]["delivered_kwh"] == 0


@pytest.mark.parametrize("intervention,component", [("repair_inverter", "inverter"),
    ("remove_attack", "communication"), ("use_redundant_solar", "battery_sensor"),
    ("reset_system", "controller")])
def test_unsupported_request_is_not_replaced_with_a_successful_intervention(intervention, component):
    result = run_experiment(SimulationSnapshot(source()), hypothesis(intervention, component), experiment_id="unsupported")
    assert result.status == "unsupported" and result.execution_tick is None
    assert result.control_telemetry == result.experimental_telemetry == []
    assert result.energy == {}


def test_unknown_parameters_missing_checkpoint_and_preincident_claims_are_explicit():
    checkpoint = SimulationSnapshot(source())
    assert run_experiment(checkpoint, hypothesis(parameters={"trusted_sensor": "nonexistent"}), experiment_id="parameters").status == "unsupported"
    assert run_experiment(None, hypothesis(), experiment_id="missing").experiment_kind == "unsupported_missing_checkpoint"
    result = run_experiment(checkpoint, hypothesis(mode="pre_incident"), experiment_id="historical")
    assert result.status == "unsupported" and not result.pre_incident_checkpoint_verified
    assert result.control_telemetry == []


def test_hidden_record_labels_do_not_select_interventions_or_enter_results(monkeypatch):
    sim = source("sensor_attack")
    first = run_experiment(SimulationSnapshot(sim), hypothesis(duration_ticks=20), experiment_id="same")
    sim.attacks._records[0].update(target_component="SECRET_ORIGIN", attack_type="SECRET_FAMILY")
    sim.evaluation_only_source = "SECRET_LABEL"
    def forbidden(*args):
        raise AssertionError("Experiment inspected schedule labels")
    monkeypatch.setattr(AttackEngine, "ground_truth", forbidden)
    monkeypatch.setattr(FaultEngine, "ground_truth", forbidden)
    second = run_experiment(SimulationSnapshot(sim), hypothesis(duration_ticks=20), experiment_id="same")
    assert asdict(first) == asdict(second)
    encoded = json.dumps(asdict(second), allow_nan=False)
    assert "SECRET_" not in encoded and "target_component" not in encoded and "ground_truth" not in encoded


def test_experiments_repeat_exactly_and_do_not_mutate_snapshot_or_existing_schedules():
    sim = source("sensor_attack")
    checkpoint = SimulationSnapshot(sim)
    before = pickle.dumps((sim, checkpoint._simulator, checkpoint._ledger))
    a = run_experiment(checkpoint, hypothesis(duration_ticks=20), experiment_id="repeat")
    b = run_experiment(checkpoint, hypothesis(duration_ticks=20), experiment_id="repeat")
    assert asdict(a) == asdict(b)
    assert pickle.dumps((sim, checkpoint._simulator, checkpoint._ledger)) == before


def test_intervention_does_not_cancel_unrelated_shutdown_or_modify_schedules():
    sim = source("inverter_fault")
    sim.inject_attack("sensor_spoof", "solar_sensor", severity=0.8, duration_ticks=60)
    snapshot = SimulationSnapshot(sim)
    result = run_experiment(snapshot, hypothesis(duration_ticks=20), experiment_id="unrelated")
    assert all(row["inverter_actual_kw"] == 0 for row in result.experimental_telemetry)
    branch = snapshot.fork("routing")
    schedules = pickle.dumps((branch._simulator.faults, branch._simulator.attacks))
    branch.advance(20, use_redundant_solar=True)
    assert pickle.dumps((branch._simulator.faults, branch._simulator.attacks)) == schedules
    # The routing option lasts for the requested advance, not forever.
    row = branch.advance(1)[0]
    assert row["measured_solar_kw"] != row["redundant_solar_kw"]


def test_differences_and_energy_are_exact_arithmetic_on_recorded_outputs():
    result = run_experiment(SimulationSnapshot(source()), hypothesis(duration_ticks=20), experiment_id="differences")
    for a, b, frame, delta in zip(result.control_telemetry, result.experimental_telemetry,
                                  result.comparison_frames, result.observable_differences):
        assert a["tick"] == b["tick"] == frame.tick == delta["tick"]
        for key in ("measured_solar_kw", "battery_energy_kwh", "controller_command_kw", "inverter_actual_kw", "delivered_kw"):
            assert delta["experimental_minus_control"][key] == b[key] - a[key]
        assert a["grid_import_kw"] is b["grid_export_kw"] is None
        assert delta["experimental_minus_control"]["grid_import_kw"] is None
    for name in ("control", "experimental"):
        assert result.energy[name]["ticks"] == 30
        assert abs(result.energy[name]["energy_balance_residual_kwh"]) < 1e-8
    assert result.energy["experimental_minus_control"]["delivered_kwh"] == result.energy["experimental"]["delivered_kwh"] - result.energy["control"]["delivered_kwh"]


@pytest.mark.parametrize("duration", [True, 0, -1, 1.5, 1001])
def test_invalid_durations_rejected(duration):
    with pytest.raises(ValueError, match="duration_ticks"):
        hypothesis(duration_ticks=duration)


def test_horizon_rejection_and_invalid_controls_do_not_advance_any_source():
    sim = source()
    checkpoint = SimulationSnapshot(sim, max_tick=20)
    before = pickle.dumps(checkpoint._simulator)
    with pytest.raises(ValueError, match="horizon"):
        run_experiment(checkpoint, hypothesis(duration_ticks=11), experiment_id="limit")
    branch = checkpoint.fork("invalid")
    with pytest.raises(ValueError, match="boolean"):
        branch.advance(1, use_redundant_solar="yes")
    assert branch.next_tick == sim.tick == 10
    assert pickle.dumps(checkpoint._simulator) == before


def test_branch_failure_is_reported_without_inventing_telemetry(monkeypatch):
    checkpoint = SimulationSnapshot(source())
    def broken(*args, **kwargs):
        raise RuntimeError("SECRET_SOURCE")
    monkeypatch.setattr(MicrogridSimulator, "step", broken)
    result = run_experiment(checkpoint, hypothesis(), experiment_id="failure")
    assert result.status == "failed" and result.control_telemetry == [] and result.end_tick is None
    assert result.execution_tick is None
    assert "SECRET_SOURCE" not in json.dumps(asdict(result))


def test_diverging_random_conditions_are_reported_as_limited(monkeypatch):
    checkpoint = SimulationSnapshot(source())
    advance = ShadowBranch.advance
    def additional_random_draw(branch, ticks, **options):
        if options:
            branch._simulator._weather.random()
        return advance(branch, ticks, **options)
    monkeypatch.setattr(ShadowBranch, "advance", additional_random_draw)
    result = run_experiment(checkpoint, hypothesis(duration_ticks=20), experiment_id="limited")
    assert result.status == "completed"
    assert not result.external_conditions_matched and not result.random_states_matched
    assert any("cannot be attributed solely" in warning for warning in result.warnings)


def test_runtime_three_branches_ledgers_history_and_database_are_untouched():
    async def scenario():
        runtime = SimulationRuntime(ServerSettings(database_path=":memory:", anomaly_model=None, source_model=None, security_model=None))
        try:
            await runtime.inject(FaultRequest(kind="sensor", mode="bias", duration_ticks=60))
            await runtime.inject_attack(AttackRequest(attack_type="replay", target_component="communication", duration_ticks=60))
            await runtime.step(10)
            checkpoint = await runtime.shadow_snapshot()
            state = runtime.state()
            database = list(runtime.store.connection.iterdump())
            before = pickle.dumps((runtime.sim, runtime.baseline, runtime.uncorrected, runtime.ledgers))
            for intervention, component in (("use_redundant_solar", "solar_sensor"), ("restore_controller_policy", "controller"), ("flush_communication", "communication")):
                assert run_experiment(checkpoint, hypothesis(intervention, component, duration_ticks=20), experiment_id=intervention).status == "completed"
            assert runtime.state() == state
            assert list(runtime.store.connection.iterdump()) == database
            assert pickle.dumps((runtime.sim, runtime.baseline, runtime.uncorrected, runtime.ledgers)) == before
        finally:
            await runtime.close()
    asyncio.run(scenario())
