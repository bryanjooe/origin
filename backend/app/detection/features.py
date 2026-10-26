"""Causal, allowlisted feature extraction: current and past observations only."""
from collections import deque
from dataclasses import dataclass
import math

import numpy as np

from app.simulator import GridConfig


FEATURE_NAMES = (
    "solar_residual_z", "soc_step_residual_z", "inverter_residual_scaled",
    "command_residual_scaled", "message_age_excess_ticks", "packet_solar_gap_scaled",
    "configuration_deviation", "unmet_fraction", "solar_change_scaled",
    "solar_residual_mean", "solar_residual_std",
)
FEATURE_VERSION = 1


def number(row, key):
    value = row[key]
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{key} must be a finite number")
    return float(value)


@dataclass
class Observation:
    tick: int
    elapsed_seconds: float
    features: dict[str, float]
    residual_checks: list[dict]

    def vector(self):
        return [self.features[name] for name in FEATURE_NAMES]


class FeatureExtractor:
    """Create a new extractor per run. GridConfig is the intended healthy config."""
    def __init__(self, config: GridConfig, window: int = 8):
        if type(window) is not int or window < 2:
            raise ValueError("window must be an integer >= 2")
        self.config = config
        self._residuals = deque(maxlen=window)
        self._previous = None

    def update(self, row: dict) -> Observation:
        c = self.config
        tick = number(row, "tick")
        elapsed = number(row, "elapsed_seconds")
        if tick < 0 or tick != int(tick):
            raise ValueError("tick must be a nonnegative integer")
        if self._previous and (tick != self._previous["tick"] + 1 or elapsed <= self._previous["elapsed"]):
            raise ValueError("Telemetry must contain consecutive, time-ordered ticks from one run")
        measured = number(row, "measured_solar_kw")
        expected = number(row, "expected_solar_kw")
        soc = number(row, "measured_soc_pct")
        power = number(row, "battery_power_kw")
        command = number(row, "controller_command_kw")
        demand = number(row, "demand_kw")
        delivered = number(row, "delivered_kw")
        requested = number(row, "inverter_requested_kw")
        actual = number(row, "inverter_actual_kw")
        if min(measured, expected, demand, delivered, requested, actual) < 0 or not 0 <= soc <= 100:
            raise ValueError("Power readings must be nonnegative and measured SOC in [0, 100]")
        solar_z = (measured - expected) / max(0.1, 0.015 * expected)
        soc_z, solar_change = 0.0, 0.0
        if self._previous:
            dt = (elapsed - self._previous["elapsed"]) / 3600
            previous_power = self._previous["power"]
            expected_delta = (-previous_power / c.discharge_efficiency if previous_power >= 0
                              else -previous_power * c.charge_efficiency) * dt / c.battery_capacity_kwh * 100
            soc_z = (soc - self._previous["soc"] - expected_delta) / 0.1
            solar_change = (measured - self._previous["solar"]) / c.solar_capacity_kw
        inputs = row["controller_inputs"]
        nominal = 0.0
        gap = 0.0
        if inputs is not None:
            received_solar = number(inputs, "solar_kw")
            received_soc = number(inputs, "soc_pct")
            deficit = number(inputs, "demand_kw") / c.inverter_efficiency - received_solar
            nominal = max(-c.charge_limit_kw, min(c.discharge_limit_kw, deficit))
            if (nominal > 0 and received_soc <= c.reserve_soc_pct) or (nominal < 0 and received_soc >= 100):
                nominal = 0.0
            gap = (received_solar - measured) / c.solar_capacity_kw
        command_residual = command - nominal
        expected_ac = min(requested, max(0, measured + power) * c.inverter_efficiency,
                          c.inverter_limit_kw)
        inverter_residual = expected_ac - actual
        age = row["message_age_seconds"]
        if age is None:
            age_excess = max(0, tick + 1 - c.communication_delay_ticks)
        else:
            age_excess = max(0, number(row, "message_age_seconds") / c.tick_seconds - c.communication_delay_ticks)
        config_deviation = max(
            abs(number(row, "applied_reserve_soc_pct") - c.reserve_soc_pct) / 100,
            abs(number(row, "applied_discharge_limit_kw") - c.discharge_limit_kw) / max(1, c.discharge_limit_kw),
            float(not row["config_integrity_ok"]),
        )
        residuals = [*self._residuals, solar_z][-self._residuals.maxlen:]
        values = (solar_z, soc_z, inverter_residual / c.solar_capacity_kw,
                  command_residual / max(1, c.charge_limit_kw, c.discharge_limit_kw),
                  age_excess, gap, config_deviation,
                  max(0, demand - delivered) / max(0.1, demand), solar_change,
                  float(np.mean(residuals)), float(np.std(residuals)))
        checks = []
        # These are explicitly rules, not learned feature importance or ML evidence.
        for signal, value, threshold, unit in (
            ("solar_measurement_residual", abs(solar_z), 5.0, "noise stddev"),
            ("soc_step_residual", abs(soc_z), 5.0, "noise stddev"),
            ("inverter_output_residual", abs(inverter_residual), 0.1 + 0.04 * c.solar_capacity_kw, "kW"),
            ("controller_policy_residual", abs(command_residual), 0.1, "kW"),
            ("stale_telemetry", age_excess, 3.0, "ticks beyond configured delay"),
            ("configuration_integrity", config_deviation, 0.01, "normalized deviation"),
        ):
            if value > threshold:
                checks.append({"signal": signal, "value": float(value), "threshold": threshold,
                               "unit": unit, "method": "residual_rule"})
        # Commit state only after the entire row has validated.
        self._residuals.append(solar_z)
        self._previous = dict(tick=tick, elapsed=elapsed, soc=soc, power=power, solar=measured)
        return Observation(int(tick), elapsed, dict(zip(FEATURE_NAMES, values)), checks)

    def transform(self, rows: list[dict]) -> list[Observation]:
        return [self.update(row) for row in rows]
