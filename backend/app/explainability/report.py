"""Deterministic explanations derived from stored incident facts and model outputs."""
from app.localization.dataset import DISPLAY_NAMES
from .evidence import describe


CHECKS = {
    "sensor": "Compare local solar/SOC readings with the irradiance reference and integrated battery-energy estimate.",
    "communication": "Compare packet source timestamps and received values with current local measurements; replay normal simulated transport.",
    "controller": "Replay the issued command against the intended operating policy using the same received packet.",
    "firmware": "Compare applied reserve/discharge settings with the intended configuration before restoring simulated settings.",
    "inverter": "Compare requested AC output, available DC bus power and independent AC metering before restoring the simulated inverter.",
    "unknown": "Obtain an independent solar/SOC or AC-output measurement and verify packet timestamps before selecting a correction.",
}


def explain(incident, graph):
    diagnosis = incident["diagnosis"]
    latest = {}
    for item in incident["evidence"]:
        latest[item["signal"]] = item
    detection = incident["trigger_detection"]
    flag_reasons = []
    if detection.get("detector_available", True) and detection["ml_status"] in ("warning", "critical"):
        flag_reasons.append(f"Isolation Forest score {detection['anomaly_score']:.5f} exceeded the "
                            f"warning threshold {detection['warning_threshold']:.5f} at detection.")
    if detection["residual_checks"]:
        flag_reasons.append("Residual-rule checks exceeded their stated limits; these checks are separate from ML.")
    if diagnosis["source"] == "unknown":
        if not diagnosis.get("source_model_available", True):
            source_statement = "No model source prediction is available. The origin remains Unknown or insufficient evidence."
        else:
            source_statement = "The source classifier abstained; the origin remains Unknown or insufficient evidence. " + " ".join(diagnosis["reasons"])
    else:
        source_statement = (f"At representative alert tick {incident['representative_tick']}, the classifier hypothesis is {DISPLAY_NAMES[diagnosis['source']]} "
                            f"with score {diagnosis['confidence']:.4f} (uncalibrated classifier probability).")
    alternatives = diagnosis["candidates"][:3] if diagnosis["source"] == "unknown" else [
        candidate for candidate in diagnosis["candidates"] if candidate["source"] != diagnosis["source"]][:2]
    questions = [CHECKS[diagnosis["source"]]]
    for alternative in alternatives:
        if alternative["source"] in CHECKS and CHECKS[alternative["source"]] not in questions:
            questions.append(CHECKS[alternative["source"]])
    return {"why_flagged": flag_reasons, "likely_source": source_statement,
            "deviations": [{"evidence_id": item["id"], "text": describe(item)} for item in latest.values()],
            "alternative_sources": alternatives, "diagnostic_checks": questions,
            "observed_symptom_sequence": [event for event in incident["timeline"] if event["event"] == "symptom_observed"],
            "potentially_affected_components": graph["potentially_affected_nodes"],
            "recovery": (f"Alerts stayed absent for {incident['recovery_ticks']} ticks; the incident is resolved as of tick "
                         f"{incident['resolved_at_tick']}. This does not prove a corrective action caused recovery."
                         if incident["status"] == "resolved" else "The incident remains open; recovery has not been confirmed."),
            "uncertainty": ["The source is a model hypothesis, not a proven root cause",
                            "Structural dependencies and temporal ordering do not establish causation",
                            "Unserved demand may reflect normal resource scarcity",
                            "Residual evidence is not feature importance or candidate-specific causal attribution"]}
