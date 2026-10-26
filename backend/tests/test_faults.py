import pytest

from app.fault_injection import Fault, FaultKind
from app.fault_injection.engine import MODES
from app.simulator import GridConfig, MicrogridSimulator
from test_simulator import assert_balance


ALL_MODES = [(kind.value, mode) for kind, modes in MODES.items() for mode in sorted(modes)]


@pytest.mark.parametrize("kind,mode", ALL_MODES)
def test_every_fault_mode_changes_observations_without_breaking_physics(kind, mode):
    config = GridConfig(start_hour=17, initial_soc_pct=60)
    normal = MicrogridSimulator(config, seed=82).run(120)
    sim = MicrogridSimulator(config, seed=82)
    sim.inject(kind, mode, severity=1, start_tick=10, duration_ticks=80)
    faulty = sim.run(120)
    assert faulty[:10] == normal[:10]
    assert any(a != b for a, b in zip(faulty[10:90], normal[10:90]))
    for row in faulty:
        assert_balance(row, config)
        assert "fault" not in row and "ground_truth" not in row and "severity" not in row
        assert "kind" not in row and "mode" not in row
    assert sim.faults.at(9) is None
    assert sim.faults.at(10) is not None
    assert sim.faults.at(89) is not None
    assert sim.faults.at(90) is None


def test_sensor_bias_propagates_to_controller_and_delivery():
    config = GridConfig(start_hour=17)
    normal = MicrogridSimulator(config).run(10)
    sim = MicrogridSimulator(config)
    sim.inject("sensor", "bias", severity=1)
    faulty = sim.run(10)
    assert faulty[0]["measured_solar_kw"] > faulty[0]["actual_solar_kw"] + 10
    assert faulty[0]["controller_command_kw"] < normal[0]["controller_command_kw"]
    assert sum(r["unmet_demand_kw"] for r in faulty) > sum(r["unmet_demand_kw"] for r in normal)


def test_stuck_reading_and_soc_bias():
    sim = MicrogridSimulator()
    sim.run(5)
    previous = sim.history[-1]["measured_solar_kw"]
    sim.inject("sensor", "stuck", duration_ticks=10)
    assert all(r["measured_solar_kw"] == previous for r in sim.run(10))
    sim.inject("sensor", "soc_bias", severity=0.5)
    row = sim.step()
    previous_soc = sim.history[-2]["battery_soc_pct"]
    assert row["measured_soc_pct"] == pytest.approx(min(100, previous_soc + 30), abs=0.2)


@pytest.mark.parametrize("mode", ["drop", "stale", "delay"])
def test_communication_age_and_recovery(mode):
    sim = MicrogridSimulator()
    sim.run(3)
    sim.inject("communication", mode, severity=1, duration_ticks=10)
    faulty = sim.run(10)
    assert max(r["message_age_seconds"] for r in faulty) >= 8 * 60
    recovered = sim.run(10)
    assert all(r["message_age_seconds"] == 0 for r in recovered)
    timestamps = [r["message_source_tick"] for r in sim.history]
    assert timestamps == sorted(timestamps)


def test_controller_configuration_and_inverter_signatures():
    sim = MicrogridSimulator(GridConfig(start_hour=17))
    sim.inject("controller", "wrong_dispatch", severity=1, duration_ticks=1)
    row = sim.step()
    assert row["controller_command_kw"] != row["nominal_command_kw"]
    sim.inject("firmware", "discharge_limit", severity=1, duration_ticks=1)
    row = sim.step()
    assert not row["config_integrity_ok"]
    assert row["applied_discharge_limit_kw"] == 0
    assert row["battery_power_kw"] <= 0
    sim.inject("inverter", "shutdown", duration_ticks=1)
    row = sim.step()
    assert row["inverter_actual_kw"] == 0 < row["inverter_requested_kw"]
    row = sim.step()
    assert row["config_integrity_ok"] and row["inverter_actual_kw"] > 0


def test_correction_flushes_bad_communications_and_preserves_energy():
    sim = MicrogridSimulator()
    sim.run(5)
    sim.inject("communication", "delay", duration_ticks=100)
    sim.run(10)
    energy = sim.battery_kwh
    tick = sim.tick
    sim.correct()
    assert sim.tick == tick and sim.battery_kwh == energy
    row = sim.step()
    assert row["message_age_seconds"] == 0
    assert sim.faults.at(tick) is None
    assert sim.events[-2]["event"] == "simulated_correction"


def test_schedule_overlap_past_and_adjacent_faults():
    sim = MicrogridSimulator()
    sim.inject("sensor", "bias", start_tick=3, duration_ticks=2)
    sim.inject("inverter", "derate", start_tick=5, duration_ticks=2)
    with pytest.raises(ValueError, match="Overlapping"):
        sim.inject("controller", "wrong_dispatch", start_tick=4, duration_ticks=1)
    sim.run(10)
    with pytest.raises(ValueError, match="past"):
        sim.inject("sensor", "bias", start_tick=0)
    assert len(sim.faults.ground_truth()) == 2


@pytest.mark.parametrize("kwargs", [
    {"severity": 0}, {"severity": 1.01}, {"severity": float("nan")},
    {"start_tick": -1}, {"start_tick": 1.5}, {"duration_ticks": 0},
    {"duration_ticks": 1.5}, {"mode": "invalid"},
])
def test_invalid_faults(kwargs):
    args = dict(kind=FaultKind.SENSOR, mode="bias", start_tick=0)
    args.update(kwargs)
    with pytest.raises(ValueError):
        Fault(**args)


def test_seeded_fault_replay_and_severity():
    def scenario(severity):
        sim = MicrogridSimulator(seed=77)
        sim.inject("inverter", "derate", severity=severity)
        return sim.run(10)
    assert scenario(0.5) == scenario(0.5)
    assert scenario(0.9)[0]["delivered_kw"] < scenario(0.2)[0]["delivered_kw"]
