"""Observable source-localization features; independent of scenario labels."""
from dataclasses import dataclass

from app.detection.features import FEATURE_NAMES as ANOMALY_FEATURES, FeatureExtractor, number
from app.simulator import GridConfig


FEATURE_VERSION = 1
FEATURE_NAMES = (*ANOMALY_FEATURES, "soc_level_residual_scaled", "soc_estimate_available",
                 "packet_soc_gap_scaled", "inverter_request_gap_scaled", "battery_power_scaled")


@dataclass
class LocalizationObservation:
    tick: int
    elapsed_seconds: float
    features: dict[str, float]
    evidence: list[dict]

    def vector(self):
        return [self.features[name] for name in FEATURE_NAMES]


class LocalizationFeatureExtractor:
    def __init__(self, config: GridConfig):
        self.config = config
        self._base = FeatureExtractor(config)
        self._previous = None
        self._estimated_soc = None

    def update(self, row: dict) -> LocalizationObservation:
        c = self.config
        tick, elapsed = number(row, "tick"), number(row, "elapsed_seconds")
        power = number(row, "battery_power_kw")
        soc = number(row, "measured_soc_pct")
        requested = number(row, "inverter_requested_kw")
        actual = number(row, "inverter_actual_kw")
        packet = row["controller_inputs"]
        packet_soc_gap = (number(packet, "soc_pct") - soc) / 100 if packet else 0.0
        estimate = self._estimated_soc
        if self._previous is None:
            # An initialized state estimate is available only from a known reset.
            estimate = c.initial_soc_pct if tick == 0 else None
        elif estimate is not None:
            dt = (elapsed - self._previous["elapsed"]) / 3600
            previous_power = self._previous["power"]
            delta = (-previous_power / c.discharge_efficiency if previous_power >= 0
                     else -previous_power * c.charge_efficiency) * dt
            estimate = max(0, min(100, estimate + delta / c.battery_capacity_kwh * 100))
        base = self._base.update(row)
        residual = (soc - estimate) / 100 if estimate is not None else 0.0
        evidence = list(base.residual_checks)
        if abs(residual) > 0.05:
            evidence.append({"signal": "soc_energy_estimate_residual", "value": abs(residual) * 100,
                             "threshold": 5.0, "unit": "percentage points", "method": "residual_rule"})
        packet_solar_gap = abs(base.features["packet_solar_gap_scaled"]) * c.solar_capacity_kw
        if packet_solar_gap > 0.1 * c.solar_capacity_kw:
            evidence.append({"signal": "packet_local_solar_disagreement", "value": packet_solar_gap,
                             "threshold": 0.1 * c.solar_capacity_kw, "unit": "kW", "method": "residual_rule"})
        features = {**base.features, "soc_level_residual_scaled": residual,
                    "soc_estimate_available": float(estimate is not None),
                    "packet_soc_gap_scaled": packet_soc_gap,
                    "inverter_request_gap_scaled": (requested - actual) / c.solar_capacity_kw,
                    "battery_power_scaled": power / max(1, c.charge_limit_kw, c.discharge_limit_kw)}
        self._estimated_soc = estimate
        self._previous = {"elapsed": elapsed, "power": power}
        return LocalizationObservation(base.tick, base.elapsed_seconds, features, evidence)

    def transform(self, rows: list[dict]):
        return [self.update(row) for row in rows]
