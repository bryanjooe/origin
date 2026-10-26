"""Evidence wording and counts derived directly from telemetry windows."""

def build_attribution(rows, prediction):
    if not rows:
        raise ValueError("Evidence requires telemetry")
    invalid = missing = duplicate = out_of_order = hash_bad = solar_disagree = soc_disagree = policy_bad = 0
    solar_gaps, soc_gaps, output_gaps, command_gaps, ages = [], [], [], [], []
    for row in rows:
        security = row.get("security_telemetry") or {}
        tag = str(security.get("auth_tag_validity", "missing")).lower()
        invalid += tag == "invalid"
        missing += tag in {"missing", "none", ""}
        duplicate += bool(security.get("duplicate_sequence"))
        out_of_order += bool(security.get("out_of_order_sequence"))
        hash_bad += not bool(security.get("config_integrity_match", True))
        solar_disagree += not bool(security.get("solar_sensors_agree", True))
        soc_disagree += not bool(security.get("battery_sensors_agree", True))
        policy_bad += not bool(security.get("command_policy_consistent", True))
        solar_gaps.append(float(security.get("solar_disagreement_kw") or 0))
        soc_gaps.append(float(security.get("soc_disagreement_pct") or 0))
        output_gaps.append(abs(float(row.get("inverter_requested_kw") or 0) -
                               float(row.get("inverter_actual_kw") or 0)))
        command_gaps.append(abs(float(row.get("controller_command_kw") or 0) -
                                float(row.get("nominal_command_kw") or 0)))
        ages.append(float(row.get("message_age_seconds") or 0))
    n = len(rows)
    def observation(name, value, unit, category, threshold=None):
        item = {"name": name, "value": value, "unit": unit, "window_ticks": n,
                "category": category, "source": "measured telemetry or controller/security log"}
        if threshold is not None:
            item["comparison_threshold"] = threshold
        return item
    toward_attack = [
        observation("Invalid authentication tags", f"{invalid} of {n}", "messages", "security", 0),
        observation("Duplicate sequence numbers", f"{duplicate} of {n}", "messages", "security", 0),
        observation("Out-of-order sequence numbers", f"{out_of_order} of {n}", "messages", "security", 0),
        observation("Configuration hash mismatches", f"{hash_bad} of {n}", "ticks", "security", 0),
        observation("Controller policy inconsistencies", f"{policy_bad} of {n}", "ticks", "security", 0),
    ]
    # Redundant disagreement can come from a faulty sensor or a deliberate
    # spoof, so it is deliberately left ambiguous rather than called a fault.
    toward_fault = []
    ambiguous = [
        observation("Missing authentication tags", f"{missing} of {n}", "messages", "security", 0),
        observation("Solar redundant-sensor disagreements", f"{solar_disagree} of {n}", "ticks", "cross-check", 0),
        observation("Battery redundant-sensor disagreements", f"{soc_disagree} of {n}", "ticks", "cross-check", 0),
        observation("Controller policy inconsistencies", f"{policy_bad} of {n}", "ticks", "controller log", 0),
        observation("Mean redundant solar gap", round(sum(solar_gaps) / n, 4), "kW", "cross-check"),
        observation("Mean redundant battery SOC gap", round(sum(soc_gaps) / n, 4), "percentage points", "cross-check"),
        observation("Mean requested-to-actual inverter gap", round(sum(output_gaps) / n, 4), "kW", "telemetry"),
        observation("Mean controller command residual", round(sum(command_gaps) / n, 4), "kW", "controller log"),
        observation("Mean message age", round(sum(ages) / n, 2), "seconds", "message metadata"),
    ]
    for group in (toward_attack, toward_fault, ambiguous):
        for item in group:
            text = item["value"]
            count = int(text.split(" of ")[0]) if isinstance(text, str) and " of " in text else None
            if count == 0:
                item["interpretation"] = "No corresponding signal observed in this window."
    return {"nature_verdict": prediction["nature"],
            "nature_confidence": prediction["nature_confidence"],
            "ranked_origin_layers": prediction.get("origin_candidates", []),
            "points_toward_attack": toward_attack,
            "points_toward_fault": toward_fault,
            "ambiguous": ambiguous,
            "statement": "These telemetry observations are indicators, not proof of intent or a proven root cause.",
            "uncertainty": ("Multiple origin candidates remain plausible."
                            if len(prediction.get("origin_candidates", [])) > 1 else None)}
