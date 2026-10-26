import pytest

from app.simulator import GridConfig, MicrogridSimulator
from app.sustainability import EnergyLedger


@pytest.mark.parametrize("fault", [None, ("sensor", "bias"), ("controller", "wrong_dispatch"),
                                  ("inverter", "efficiency"), ("firmware", "reserve_threshold")])
def test_ledger_conserves_energy_and_renewable_provenance(fault):
    sim = MicrogridSimulator(GridConfig(start_hour=0))
    if fault:
        sim.inject(*fault, severity=1, start_tick=500, duration_ticks=800)
    ledger = EnergyLedger(sim.config)
    for row in sim.run(1440):
        ledger.update(row)
        snapshot = ledger.snapshot()
        assert snapshot["battery_energy_kwh"] == pytest.approx(row["battery_energy_kwh"], abs=1e-9)
        assert 0 <= snapshot["renewable_stored_kwh"] <= snapshot["battery_energy_kwh"] + 1e-9
    assert snapshot["energy_balance_residual_kwh"] == pytest.approx(0, abs=1e-8)
    assert snapshot["renewable_energy_balance_residual_kwh"] == pytest.approx(0, abs=1e-8)
    assert snapshot["renewable_delivered_kwh"] <= snapshot["solar_generated_kwh"] + 1e-9
    assert snapshot["delivered_kwh"] + snapshot["unmet_demand_kwh"] == pytest.approx(snapshot["demand_kwh"])
    assert snapshot["observed_discharge_efficiency"] == pytest.approx(sim.config.discharge_efficiency)


def test_initial_battery_is_not_falsely_counted_as_renewable():
    sim = MicrogridSimulator(GridConfig(start_hour=0))
    ledger = EnergyLedger(sim.config)
    for row in sim.run(30):
        ledger.update(row)
    result = ledger.snapshot()
    assert result["delivered_kwh"] > 0
    assert result["solar_generated_kwh"] == result["renewable_delivered_kwh"] == 0
    assert result["initial_unknown_battery_energy_kwh"] == 14.4


def test_empty_ledger_uses_null_efficiencies_not_invented_measurements():
    result = EnergyLedger(GridConfig()).snapshot()
    assert result["observed_charge_efficiency"] is None
    assert result["observed_discharge_efficiency"] is None
    assert result["demand_served_fraction"] is None
