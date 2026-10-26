"""Energy accounting with proportional renewable/unknown provenance mixing."""
from app.simulator import GridConfig


class EnergyLedger:
    def __init__(self, config: GridConfig):
        self.config = config
        self.energy = config.battery_capacity_kwh * config.initial_soc_pct / 100
        self.initial_energy = self.energy
        self.renewable_stored = 0.0  # Initial storage provenance is unknown.
        self.ticks = 0
        self.totals = dict.fromkeys(("solar_generated_kwh", "renewable_delivered_kwh", "delivered_kwh", "demand_kwh",
                                    "unmet_demand_kwh", "unused_dc_kwh", "solar_curtailed_kwh", "inverter_loss_kwh",
                                    "battery_loss_kwh", "excess_ac_kwh", "charge_input_kwh", "charge_stored_kwh",
                                    "discharge_output_kwh", "discharge_withdrawn_kwh", "renewable_unused_dc_kwh",
                                    "renewable_inverter_loss_kwh", "renewable_battery_loss_kwh", "renewable_excess_ac_kwh"), 0.0)

    def update(self, row):
        c, totals = self.config, self.totals
        dt = c.tick_seconds / 3600
        charge = max(0, -row["battery_power_kw"]) * dt
        discharge = max(0, row["battery_power_kw"]) * dt
        withdrawn = discharge / c.discharge_efficiency
        fraction = self.renewable_stored / self.energy if self.energy > 1e-12 else 0.0
        renewable_discharge = discharge * fraction
        self.renewable_stored = max(0, self.renewable_stored - withdrawn * fraction) + charge * c.charge_efficiency
        self.energy += charge * c.charge_efficiency - withdrawn
        solar_dc = max(0, row["actual_solar_kw"] - charge / dt)
        dc = solar_dc + discharge / dt
        renewable_fraction = min(1, (solar_dc + renewable_discharge / dt) / dc) if dc > 1e-12 else 0.0
        totals["solar_generated_kwh"] += row["actual_solar_kw"] * dt
        totals["renewable_delivered_kwh"] += row["delivered_kw"] * dt * renewable_fraction
        for target, source in (("delivered_kwh", "delivered_kw"), ("demand_kwh", "demand_kw"),
                               ("unmet_demand_kwh", "unmet_demand_kw"), ("unused_dc_kwh", "curtailed_dc_kw"),
                               ("inverter_loss_kwh", "inverter_loss_kw"), ("excess_ac_kwh", "excess_ac_kw")):
            totals[target] += row[source] * dt
        totals["solar_curtailed_kwh"] += row["curtailed_dc_kw"] * dt * (solar_dc / dc if dc > 1e-12 else 0)
        totals["renewable_unused_dc_kwh"] += row["curtailed_dc_kw"] * dt * renewable_fraction
        totals["renewable_inverter_loss_kwh"] += row["inverter_loss_kw"] * dt * renewable_fraction
        totals["renewable_excess_ac_kwh"] += row["excess_ac_kw"] * dt * renewable_fraction
        totals["renewable_battery_loss_kwh"] += (withdrawn - discharge) * fraction + charge * (1 - c.charge_efficiency)
        totals["battery_loss_kwh"] += row["battery_loss_kwh"]
        totals["charge_input_kwh"] += charge
        totals["charge_stored_kwh"] += charge * c.charge_efficiency
        totals["discharge_output_kwh"] += discharge
        totals["discharge_withdrawn_kwh"] += withdrawn
        self.ticks += 1

    def snapshot(self):
        totals = self.totals
        balance = (totals["solar_generated_kwh"] - totals["delivered_kwh"] - totals["unused_dc_kwh"]
                   - totals["inverter_loss_kwh"] - totals["battery_loss_kwh"] - totals["excess_ac_kwh"]
                   - (self.energy - self.initial_energy))
        return {**totals, "ticks": self.ticks, "battery_energy_kwh": self.energy,
                "renewable_stored_kwh": self.renewable_stored,
                "initial_unknown_battery_energy_kwh": self.initial_energy,
                "battery_energy_change_kwh": self.energy - self.initial_energy,
                "energy_balance_residual_kwh": balance,
                "renewable_energy_balance_residual_kwh": (totals["solar_generated_kwh"] - totals["renewable_delivered_kwh"]
                    - totals["renewable_unused_dc_kwh"] - totals["renewable_inverter_loss_kwh"]
                    - totals["renewable_battery_loss_kwh"] - totals["renewable_excess_ac_kwh"] - self.renewable_stored),
                "solar_capture_fraction": (1 - totals["solar_curtailed_kwh"] / totals["solar_generated_kwh"]) if totals["solar_generated_kwh"] else None,
                "renewable_delivery_fraction_of_generated": totals["renewable_delivered_kwh"] / totals["solar_generated_kwh"] if totals["solar_generated_kwh"] else None,
                "observed_charge_efficiency": totals["charge_stored_kwh"] / totals["charge_input_kwh"] if totals["charge_input_kwh"] else None,
                "observed_discharge_efficiency": totals["discharge_output_kwh"] / totals["discharge_withdrawn_kwh"] if totals["discharge_withdrawn_kwh"] else None,
                "configured_round_trip_efficiency": self.config.charge_efficiency * self.config.discharge_efficiency,
                "demand_served_fraction": totals["delivered_kwh"] / totals["demand_kwh"] if totals["demand_kwh"] else None}
