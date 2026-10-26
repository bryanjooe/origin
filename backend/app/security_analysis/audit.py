"""Seeded feature-separability audit; scenario labels are used only for grouping."""

from collections import defaultdict
from statistics import mean


AUDIT_FEATURES = (
    "auth_invalid_rate", "auth_missing_rate", "sequence_anomaly_rate",
    "config_hash_mismatch_rate", "solar_sensor_disagreement_rate",
    "battery_sensor_disagreement_rate", "policy_inconsistency_rate",
    "solar_redundancy_gap_mean_scaled", "soc_redundancy_gap_mean_scaled",
    "controller_command_residual_mean_scaled", "inverter_output_gap_mean_scaled",
    "communication_delay_excess_ticks", "cross_signal_inconsistency_rate",
)


def summarize_telemetry(runs):
    """Return per-run observable rates/means, then group only for reporting."""
    per_run, groups = [], defaultdict(list)
    for run in runs:
        if run.nature == "normal":
            rows = run.telemetry
            group_names = ["normal"]
        else:
            stop = min(len(run.telemetry), run.start_tick + run.duration_ticks)
            rows = run.telemetry[run.start_tick:stop]
            if run.nature == "fault":
                group_names = [f"fault:{run.scenario_type}/{run.mode}"]
            else:
                group_names = [f"attack:{run.scenario_type}/{run.stealth_level}",
                               f"attack_target:{run.scenario_type}/{run.stealth_level}/{run.target_component}"]
        values = {name: [] for name in AUDIT_FEATURES}
        for row in rows:
            sec = row.get("security_telemetry") or {}
            values["auth_invalid_rate"].append(float(sec.get("auth_tag_validity") == "invalid"))
            values["auth_missing_rate"].append(float(sec.get("auth_tag_validity") == "missing"))
            values["sequence_anomaly_rate"].append(float(bool(sec.get("duplicate_sequence") or
                                                                sec.get("out_of_order_sequence"))))
            values["config_hash_mismatch_rate"].append(float(not sec.get("config_integrity_match", True)))
            values["solar_sensor_disagreement_rate"].append(float(not sec.get("solar_sensors_agree", True)))
            values["battery_sensor_disagreement_rate"].append(float(not sec.get("battery_sensors_agree", True)))
            values["policy_inconsistency_rate"].append(float(not sec.get("command_policy_consistent", True)))
            values["solar_redundancy_gap_mean_scaled"].append(
                abs(float(sec.get("solar_disagreement_kw") or 0)) / run.config.solar_capacity_kw)
            values["soc_redundancy_gap_mean_scaled"].append(
                abs(float(sec.get("soc_disagreement_pct") or 0)) / 100)
            values["controller_command_residual_mean_scaled"].append(
                abs(float(row.get("controller_command_kw") or 0) -
                    float(row.get("nominal_command_kw") or 0)) / run.config.solar_capacity_kw)
            values["inverter_output_gap_mean_scaled"].append(
                abs(float(row.get("inverter_requested_kw") or 0) -
                    float(row.get("inverter_actual_kw") or 0)) / run.config.solar_capacity_kw)
            values["communication_delay_excess_ticks"].append(max(0,
                float(row.get("communication_latency_seconds") or 0) / run.config.tick_seconds -
                run.config.communication_delay_ticks))
            values["cross_signal_inconsistency_rate"].append(float(
                abs(float(sec.get("solar_disagreement_kw") or 0)) / run.config.solar_capacity_kw > 0.025 or
                abs(float(sec.get("soc_disagreement_pct") or 0)) / 100 > 0.025 or
                abs(float(row.get("inverter_requested_kw") or 0) -
                    float(row.get("inverter_actual_kw") or 0)) / run.config.solar_capacity_kw > 0.05))
        run_values = {name: mean(items) if items else 0.0 for name, items in values.items()}
        record = {"run_id": run.run_id, "nature": run.nature,
                  "groups": group_names, **run_values}
        per_run.append(record)
        for group in group_names:
            groups[group].append(run_values)
    grouped = {key: {"runs": len(items), **{name: mean(row[name] for row in items)
                                             for name in AUDIT_FEATURES}}
               for key, items in sorted(groups.items())}
    attacks = [row for row in per_run if row["nature"] == "attack"]
    benign = [row for row in per_run if row["nature"] != "attack"]
    perfect = []
    for name in AUDIT_FEATURES:
        attack_min = min(row[name] for row in attacks)
        attack_max = max(row[name] for row in attacks)
        benign_min = min(row[name] for row in benign)
        benign_max = max(row[name] for row in benign)
        if attack_min > benign_max or attack_max < benign_min:
            perfect.append({"feature": name, "attack_range": [attack_min, attack_max],
                            "normal_and_fault_range": [benign_min, benign_max]})
    return {"provenance": "seeded synthetic telemetry; labels used only to group audit rows",
            "window": "active event rows for faults/attacks; entire run for normal",
            "features": list(AUDIT_FEATURES), "per_group_mean_rates_and_signals": grouped,
            "perfect_global_single_feature_separators": perfect,
            "run_level_values_for_threshold_review": per_run}
