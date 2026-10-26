import math

import pytest

from app.simulator import GridConfig, MicrogridSimulator


def assert_balance(row, config):
    dt = config.tick_seconds / 3600
    # PV energy = load + stored-energy change + all losses/unused energy.
    rhs = ((row["delivered_kw"] + row["excess_ac_kw"] + row["curtailed_dc_kw"]
            + row["inverter_loss_kw"]) * dt + row["battery_delta_kwh"]
           + row["battery_loss_kwh"])
    assert row["actual_solar_kw"] * dt == pytest.approx(rhs, abs=1e-10)
    assert row["delivered_kw"] + row["unmet_demand_kw"] == pytest.approx(row["demand_kw"])
    assert config.reserve_soc_pct - 1e-8 <= row["battery_soc_pct"] <= 100 + 1e-8
    assert -config.charge_limit_kw <= row["battery_power_kw"] <= config.discharge_limit_kw
    assert 0 <= row["inverter_actual_kw"] <= config.inverter_limit_kw
    for key in ("actual_solar_kw", "delivered_kw", "unmet_demand_kw", "inverter_loss_kw",
                "curtailed_dc_kw", "excess_ac_kw", "battery_loss_kwh"):
        assert row[key] >= -1e-10


def test_day_night_physics_and_energy_conservation():
    sim = MicrogridSimulator(GridConfig(start_hour=0))
    rows = sim.run(2880)
    for row in rows:
        assert_balance(row, sim.config)
        assert row["expected_solar_kw"] == pytest.approx(row["irradiance"] * sim.config.solar_capacity_kw)
        assert row["solar_voltage_v"] * row["solar_current_a"] / 1000 == pytest.approx(row["actual_solar_kw"])
        assert 0 <= row["irradiance"] <= 1
    assert rows[0]["actual_solar_kw"] == 0
    assert rows[720]["actual_solar_kw"] > 0
    assert any(r["battery_power_kw"] > 0 for r in rows)
    assert any(r["battery_power_kw"] < 0 for r in rows)


@pytest.mark.parametrize("soc", [0, 10, 99.9, 100])
@pytest.mark.parametrize("tick_seconds", [1, 60, 3600])
def test_battery_boundaries(soc, tick_seconds):
    sim = MicrogridSimulator(GridConfig(initial_soc_pct=soc, reserve_soc_pct=0,
                                       tick_seconds=tick_seconds))
    for row in sim.run(100):
        assert_balance(row, sim.config)


def test_normal_measurements_commands_and_conversion():
    sim = MicrogridSimulator()
    for row in sim.run(50):
        assert row["config_integrity_ok"]
        assert row["message_age_seconds"] == 0
        assert row["controller_command_kw"] == row["nominal_command_kw"]
        assert abs(row["measured_solar_kw"] - row["actual_solar_kw"]) < 0.7
        dc_available = row["actual_solar_kw"] + row["battery_power_kw"]
        assert row["inverter_actual_kw"] <= dc_available * sim.config.inverter_efficiency + 1e-9
        assert row["inverter_loss_kw"] == pytest.approx(
            row["inverter_actual_kw"] * (1 / sim.config.inverter_efficiency - 1))


def test_determinism_reset_and_weather_independence():
    sim = MicrogridSimulator(seed=15)
    expected = sim.run(100)
    sim.reset()
    assert sim.run(100) == expected
    assert MicrogridSimulator(seed=15).run(100) == expected
    assert MicrogridSimulator(seed=16).run(100) != expected
    sim.reset()
    sim.inject("sensor", "noise", duration_ticks=100)
    actual = sim.run(100)
    assert [r["actual_solar_kw"] for r in actual] == [r["actual_solar_kw"] for r in expected]
    assert [r["demand_kw"] for r in actual] == [r["demand_kw"] for r in expected]
    sim.reset(seed=16)
    assert sim.history == [] and sim.events == [] and sim.tick == 0
    assert sim.faults.ground_truth() == []


@pytest.mark.parametrize("kwargs", [
    {"tick_seconds": 0}, {"battery_capacity_kwh": -1}, {"initial_soc_pct": 101},
    {"charge_efficiency": 1.1}, {"inverter_efficiency": 0}, {"start_hour": 24},
    {"base_demand_kw": math.nan}, {"charge_limit_kw": -1},
    {"packet_loss_probability": 2}, {"communication_delay_ticks": 0.5},
    {"solar_capacity_kw": math.inf}, {"reserve_soc_pct": 61},
])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        GridConfig(**kwargs)


def test_no_telemetry_fails_safe():
    sim = MicrogridSimulator(GridConfig(packet_loss_probability=1))
    for row in sim.run(10):
        assert row["controller_inputs"] is None
        assert row["message_age_seconds"] is None
        assert row["controller_command_kw"] == row["inverter_requested_kw"] == 0
        assert row["controller_rule"] == "await_telemetry"
        assert_balance(row, sim.config)


def test_configured_packet_delay_and_timestamp_order():
    sim = MicrogridSimulator(GridConfig(communication_delay_ticks=2))
    rows = sim.run(5)
    assert rows[0]["controller_inputs"] is None
    assert rows[1]["controller_inputs"] is None
    assert rows[2]["message_source_tick"] == 0
    assert rows[4]["message_age_seconds"] == 120


@pytest.mark.parametrize("ticks", [-1, 1.5, True])
def test_invalid_run_length(ticks):
    with pytest.raises(ValueError):
        MicrogridSimulator().run(ticks)
