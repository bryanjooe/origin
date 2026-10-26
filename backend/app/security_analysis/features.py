"""Causal, observable-only features for post-detector incident windows."""

from collections.abc import Mapping, Sequence
import math


FEATURE_VERSION = 1
WINDOW_TICKS = 20
FEATURE_NAMES = (
    "auth_invalid_rate", "auth_missing_rate", "sequence_anomaly_rate",
    "config_hash_mismatch_rate", "solar_sensor_disagreement_rate",
    "battery_sensor_disagreement_rate", "policy_inconsistency_rate",
    "packet_drop_rate", "communication_delay_excess_ticks",
    "message_age_excess_ticks", "solar_redundancy_gap_mean_scaled",
    "solar_redundancy_gap_max_scaled", "soc_redundancy_gap_mean_scaled",
    "soc_redundancy_gap_max_scaled", "controller_command_residual_mean_scaled",
    "controller_command_residual_max_scaled", "inverter_output_gap_mean_scaled",
    "inverter_output_gap_max_scaled", "battery_soc_energy_residual_mean_scaled",
    "battery_soc_energy_residual_max_scaled", "unmet_demand_rate",
    "onset_sharpness", "signal_persistence", "goal_directed_command_rate",
    "cross_signal_inconsistency_rate",
)

_FORBIDDEN = ("attack", "fault", "ground_truth", "scenario_label", "engine_record")


def _reject_hidden(value):
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(token in normalized for token in _FORBIDDEN):
                raise ValueError(f"Hidden scenario field is forbidden in features: {key}")
            _reject_hidden(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_hidden(child)


def _mean(values):
    return sum(values) / len(values) if values else 0.0


def _number(mapping, key, default=0.0):
    value = mapping.get(key, default)
    if value is None:
        return float(default)
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{key} must be finite numeric telemetry")
    return float(value)


class SecurityWindowFeatures:
    """Extract one causal feature vector from the latest <=20 telemetry rows."""

    def __init__(self, *, solar_capacity_kw=12.0, battery_capacity_kwh=24.0,
                 tick_seconds=60.0, communication_delay_ticks=0):
        if min(solar_capacity_kw, battery_capacity_kwh, tick_seconds) <= 0:
            raise ValueError("Physical scales must be positive")
        self.solar_capacity_kw = solar_capacity_kw
        self.battery_capacity_kwh = battery_capacity_kwh
        self.tick_seconds = tick_seconds
        self.communication_delay_ticks = communication_delay_ticks

    def extract(self, rows: Sequence[dict]):
        return extract_window(rows, solar_capacity_kw=self.solar_capacity_kw,
                              battery_capacity_kwh=self.battery_capacity_kwh,
                              tick_seconds=self.tick_seconds,
                              communication_delay_ticks=self.communication_delay_ticks)


def extract_window(rows: Sequence[dict], *, solar_capacity_kw=12.0,
                   battery_capacity_kwh=24.0, tick_seconds=60.0,
                   communication_delay_ticks=0, charge_efficiency=0.95,
                   discharge_efficiency=0.95):
    if not rows:
        raise ValueError("At least one observable telemetry row is required")
    selected = list(rows[-WINDOW_TICKS:])
    for row in selected:
        _reject_hidden(row)
    solar_gaps, soc_gaps, command_residuals, inverter_gaps = [], [], [], []
    energy_residuals, ages, delays, sharpness_values, goal_commands = [], [], [], [], []
    auth_invalid = auth_missing = seq = hash_bad = solar_bad = soc_bad = policy_bad = drops = unmet = 0
    cross_bad = 0
    previous = None
    for row in selected:
        security = row.get("security_telemetry") or {}
        tag = str(security.get("auth_tag_validity", "missing")).lower()
        auth_invalid += tag == "invalid"
        auth_missing += tag in {"missing", "none", ""}
        seq += bool(security.get("duplicate_sequence") or security.get("out_of_order_sequence"))
        hash_bad += not bool(security.get("config_integrity_match", True))
        solar_bad += not bool(security.get("solar_sensors_agree", True))
        soc_bad += not bool(security.get("battery_sensors_agree", True))
        policy_bad += not bool(security.get("command_policy_consistent", True))
        drops += bool(row.get("packet_dropped", False))
        unmet += _number(row, "unmet_demand_kw") > 0.15
        solar_gap = abs(_number(security, "solar_disagreement_kw")) / solar_capacity_kw
        soc_gap = abs(_number(security, "soc_disagreement_pct")) / 100
        solar_gaps.append(solar_gap)
        soc_gaps.append(soc_gap)
        requested, actual = _number(row, "inverter_requested_kw"), _number(row, "inverter_actual_kw")
        inverter_gap = abs(requested - actual) / solar_capacity_kw
        inverter_gaps.append(inverter_gap)
        command_gap = abs(_number(row, "controller_command_kw") - _number(row, "nominal_command_kw"))
        command_residuals.append(command_gap / max(1.0, solar_capacity_kw))
        ages.append(max(0.0, _number(row, "message_age_seconds") / tick_seconds - communication_delay_ticks))
        delays.append(max(0.0, _number(row, "communication_latency_seconds") / tick_seconds - communication_delay_ticks))
        if previous is not None:
            dt_hours = (_number(row, "elapsed_seconds") - _number(previous, "elapsed_seconds")) / 3600
            observed_soc_delta = _number(row, "measured_soc_pct") - _number(previous, "measured_soc_pct")
            power = _number(previous, "battery_power_kw")
            expected_power_delta = (-power / discharge_efficiency if power >= 0
                                    else -power * charge_efficiency)
            expected_delta = expected_power_delta * dt_hours / battery_capacity_kwh * 100
            energy_residuals.append(abs(observed_soc_delta - expected_delta) / 100)
            previous_gap = abs(_number(previous, "inverter_requested_kw") - _number(previous, "inverter_actual_kw")) / solar_capacity_kw
            sharpness_values.append(abs(inverter_gap - previous_gap))
        command = _number(row, "controller_command_kw")
        goal_commands.append(float(command > 0.1))
        # Cross-checks only use independently measured signals and controller
        # logs. Neither simulation engine schedule nor ground truth is read.
        cross_bad += solar_gap > 0.025 or soc_gap > 0.025 or inverter_gap > 0.05
        previous = row
    n = len(selected)
    features = {
        "auth_invalid_rate": auth_invalid / n,
        "auth_missing_rate": auth_missing / n,
        "sequence_anomaly_rate": seq / n,
        "config_hash_mismatch_rate": hash_bad / n,
        "solar_sensor_disagreement_rate": solar_bad / n,
        "battery_sensor_disagreement_rate": soc_bad / n,
        "policy_inconsistency_rate": policy_bad / n,
        "packet_drop_rate": drops / n,
        "communication_delay_excess_ticks": _mean(delays),
        "message_age_excess_ticks": _mean(ages),
        "solar_redundancy_gap_mean_scaled": _mean(solar_gaps),
        "solar_redundancy_gap_max_scaled": max(solar_gaps, default=0.0),
        "soc_redundancy_gap_mean_scaled": _mean(soc_gaps),
        "soc_redundancy_gap_max_scaled": max(soc_gaps, default=0.0),
        "controller_command_residual_mean_scaled": _mean(command_residuals),
        "controller_command_residual_max_scaled": max(command_residuals, default=0.0),
        "inverter_output_gap_mean_scaled": _mean(inverter_gaps),
        "inverter_output_gap_max_scaled": max(inverter_gaps, default=0.0),
        "battery_soc_energy_residual_mean_scaled": _mean(energy_residuals),
        "battery_soc_energy_residual_max_scaled": max(energy_residuals, default=0.0),
        "unmet_demand_rate": unmet / n,
        "onset_sharpness": _mean(sharpness_values),
        "signal_persistence": sum(value > 0.025 for value in inverter_gaps) / n,
        "goal_directed_command_rate": _mean(goal_commands),
        "cross_signal_inconsistency_rate": cross_bad / n,
    }
    if tuple(features) != FEATURE_NAMES or not all(math.isfinite(v) for v in features.values()):
        raise ValueError("Feature schema mismatch or non-finite feature")
    return features
