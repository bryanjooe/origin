"""Evidence records use only current measurements and model-reported residuals."""
import math


SIGNAL_NODES = {
    "solar_measurement_residual": ["solar_sensor"],
    "soc_step_residual": ["battery_sensor"],
    "soc_energy_estimate_residual": ["battery_sensor"],
    "inverter_output_residual": ["inverter"],
    "controller_policy_residual": ["controller"],
    "stale_telemetry": ["communication"],
    "configuration_integrity": ["firmware"],
    "packet_local_solar_disagreement": ["communication", "solar_sensor"],
    "unmet_demand": ["delivered"],
}
SAMPLE_FIELDS = (
    "tick", "elapsed_seconds", "expected_solar_kw", "measured_solar_kw", "measured_soc_pct",
    "battery_power_kw", "demand_kw", "delivered_kw", "unmet_demand_kw", "controller_command_kw",
    "inverter_requested_kw", "inverter_actual_kw", "message_age_seconds", "message_source_tick",
    "applied_reserve_soc_pct", "applied_discharge_limit_kw", "config_integrity_ok",
)


def observable_sample(row):
    result = {field: row[field] for field in SAMPLE_FIELDS}
    packet = row.get("controller_inputs")
    result["controller_inputs"] = ({key: packet[key] for key in ("source_tick", "solar_kw", "soc_pct", "demand_kw")}
                                   if packet is not None else None)
    for key, value in result.items():
        if key != "controller_inputs" and isinstance(value, (float, int)) and not math.isfinite(value):
            raise ValueError(f"Non-finite observable: {key}")
    if result["controller_inputs"] is not None:
        for value in result["controller_inputs"].values():
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Controller packet values must be finite numbers")
    return result


def collect_evidence(sample, detection, source):
    """Inputs are trusted outputs of the fitted models, never generator labels."""
    rules = [*detection.get("residual_checks", []),
             *(source.get("supporting_observations", []) if source else [])]
    seen, evidence = set(), []
    for rule in rules:
        signal = rule["signal"]
        if signal not in SIGNAL_NODES or signal in seen:
            continue
        seen.add(signal)
        value, threshold = float(rule["value"]), float(rule["threshold"])
        if not math.isfinite(value) or not math.isfinite(threshold) or value <= threshold:
            raise ValueError("Residual evidence must be finite and exceed its stated threshold")
        evidence.append({"id": f"t{sample['tick']}:{signal}", "tick": sample["tick"],
                         "elapsed_seconds": sample["elapsed_seconds"], "signal": signal,
                         "nodes": SIGNAL_NODES[signal], "value": value, "threshold": threshold,
                         "unit": rule["unit"], "kind": "residual_observation", "sample": sample})
    if sample["unmet_demand_kw"] > 0.1:
        evidence.append({"id": f"t{sample['tick']}:unmet_demand", "tick": sample["tick"],
                         "elapsed_seconds": sample["elapsed_seconds"], "signal": "unmet_demand",
                         "nodes": ["delivered"], "value": sample["unmet_demand_kw"], "threshold": 0.1,
                         "unit": "kW", "kind": "observed_impact", "sample": sample})
    return evidence


def describe(evidence):
    sample, signal = evidence["sample"], evidence["signal"]
    if signal == "solar_measurement_residual":
        return (f"Solar sensor reports {sample['measured_solar_kw']:.3f} kW versus "
                f"{sample['expected_solar_kw']:.3f} kW from the irradiance reference.")
    if signal == "inverter_output_residual":
        return (f"The inverter requests {sample['inverter_requested_kw']:.3f} kW and produces "
                f"{sample['inverter_actual_kw']:.3f} kW; the availability-adjusted residual is "
                f"{evidence['value']:.3f} kW (limit {evidence['threshold']:.3f} kW).")
    if signal == "unmet_demand":
        return (f"Demand is {sample['demand_kw']:.3f} kW and delivery {sample['delivered_kw']:.3f} kW, "
                f"leaving {sample['unmet_demand_kw']:.3f} kW unserved. This can also occur during normal scarcity.")
    if signal == "stale_telemetry":
        age = sample["message_age_seconds"]
        return (f"The controller packet age is {age:.1f} seconds." if age is not None else
                "No timestamped controller packet is available.")
    if signal == "controller_policy_residual":
        return (f"Issued battery command is {sample['controller_command_kw']:.3f} kW; its difference "
                f"from the reconstructed intended policy is {evidence['value']:.3f} kW.")
    if signal == "configuration_integrity":
        return (f"Applied reserve is {sample['applied_reserve_soc_pct']:.2f}% and discharge limit "
                f"{sample['applied_discharge_limit_kw']:.3f} kW; normalized integrity deviation "
                f"is {evidence['value']:.3f} (limit {evidence['threshold']:.3f}).")
    return (f"{signal.replace('_', ' ').capitalize()} is {evidence['value']:.3f} "
            f"{evidence['unit']} (limit {evidence['threshold']:.3f}).")
