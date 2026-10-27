"""Report only approved observations and existing ShadowTwin assessments."""
from dataclasses import asdict

from app.shadowtwin.foundation import ComparisonFrame
from app.shadowtwin.experiments import _deltas


def observation_groups(observations):
    groups = {}
    for observation in observations:
        key = (observation.signal, observation.tick, observation.value, observation.threshold, observation.unit)
        item = groups.setdefault(key, {key: value for key, value in asdict(observation).items() if key not in ("provenance", "evidence_id")})
        item.setdefault("provenance", [])
        if observation.provenance not in item["provenance"]:
            item["provenance"].append(observation.provenance)
        item.setdefault("evidence_ids", [])
        if observation.evidence_id and observation.evidence_id not in item["evidence_ids"]:
            item["evidence_ids"].append(observation.evidence_id)
    return list(groups.values())


def experiment_observations(result):
    """Reuse the existing observable projection; raw schedules/extra keys never pass."""
    frames, differences = [], []
    try:
        for control, experimental in zip(result.control_telemetry, result.experimental_telemetry):
            frame = ComparisonFrame.from_rows(result.experiment_id, {"control": control, "experimental": experimental})
            frames.append({"tick": frame.tick, **frame.telemetry})
            differences.append({"tick": frame.tick, "experimental_minus_control": _deltas(frame.telemetry["control"], frame.telemetry["experimental"])})
    except (KeyError, TypeError, ValueError):
        # The comparison assessment records invalid/incomplete measurements.
        return {"paired_telemetry": [], "measurement_differences": [], "projection_available": False}
    return {"paired_telemetry": frames, "measurement_differences": differences, "projection_available": bool(frames)}


def fusion_report(context, steps, comparison, initial_plan=None):
    items = comparison.get("hypotheses", []) if comparison else []
    eligible = [item for item in items if item.get("eligible_for_ranking")]
    adverse = [item for item in items if item.get("new_or_worsened_abnormalities") or
               "Worsened" in item.get("intervention_outcome", "") or "worsened" in item.get("intervention_outcome", "") or
               "different_candidate_group" in item.get("model_agreement", {}).values()]
    improved = [item for item in eligible if item.get("intervention_outcome") == "Relevant symptoms reduced"]
    if adverse:
        effect = "Mixed evidence"
    elif improved:
        effect = "Intervention supported"
    elif eligible:
        effect = "No relevant symptom improvement"
    else:
        effect = "Insufficient experimental evidence"
    best = None
    if comparison and comparison.get("status") == "Ranked prospective evidence":
        front = next((group for group in comparison.get("intervention_ranking", []) if group["position"] == 1), None)
        if front and len(front["hypothesis_ids"]) == 1:
            best = next((item["intervention"] for item in items if item["hypothesis_id"] == front["hypothesis_ids"][0]), None)
    models = [{"model": record.name, "scope": record.scope, "original_fields": dict(record.fields),
               "reported_candidates": [{"label": label, "model_score": score} for label, score in record.candidates]}
              for record in context.model_records]
    initial = {"anomaly_status": context.current_status, "phase1_prediction": context.phase1_prediction,
        "stage_b_origin": context.stage_b_origin, "stage_b_nature": context.stage_b_nature,
        "original_model_records": models, "observable_abnormalities": observation_groups(context.current_observations)}
    findings = [{key: item.get(key) for key in ("hypothesis_id", "intervention", "experiment_status", "eligible_for_ranking",
                 "intervention_outcome", "evidence_assessment", "physical_observations", "delivered_energy_difference_kwh",
                 "model_agreement", "exclusion_reason", "explanation")} for item in items]
    limitations = [*context.limitations, *(comparison.get("limitations", []) if comparison else []),
        "Initial classifiers, residuals and security logs may share telemetry. They are not independent confirmations and no scores are averaged.",
        "Removing a resolved target from follow-up planning describes a virtual outcome, not a change to live measurements.",
        "All experiments are prospective from one common checkpoint; historical source and malicious intent are not established.",
        "Future execution requires fresh context validation; no live recovery action has been performed."]
    for item in items:
        limitations.extend(item.get("warnings", []))
        limitations.extend((item.get("experiment") or {}).get("limitations", []))
    considered = [*steps, *((initial_plan or {}).get("selected_experiments", [])), *((initial_plan or {}).get("alternative_investigations", []))]
    for step in considered:
        limitations.extend(step["limitations"])
    unresolved = []
    for step in considered:
        for hypothesis in step["related_hypotheses"]:
            if hypothesis not in unresolved:
                unresolved.append(hypothesis)
    mechanisms = {step["intervention_id"] for step in steps}
    recommendations = []
    if "restore_controller_policy" in mechanisms:
        recommendations.append("Review controller policy/configuration and independently verify its received inputs; no live settings were changed.")
    if "use_redundant_solar" in mechanisms:
        recommendations.append("Verify sensor integrity using an independent trusted measurement; the redundant sensor alone cannot establish malicious intent.")
    if "flush_communication" in mechanisms:
        recommendations.append("Inspect authenticated communication records. Temporary buffer clearing does not establish removal of an ongoing attack.")
    if not recommendations:
        recommendations.append("Continue monitoring or obtain dated, independent component evidence before requesting another virtual test.")
    return {"initial_ai_assessment": initial,
        "evidence_fusion": {"initial_observable_evidence": observation_groups(context.current_observations),
            "experimental_findings": findings,
            "contradictory_observations": [{"intervention_id": item["intervention"], "new_or_worsened_abnormalities": item.get("new_or_worsened_abnormalities", []),
                "delivered_energy_difference_kwh": item.get("delivered_energy_difference_kwh"), "model_agreement": item.get("model_agreement", {})} for item in adverse],
            "unresolved_hypotheses": unresolved, "limitations": list(dict.fromkeys(limitations))},
        "final_assessment": {"most_useful_tested_intervention": best, "intervention_effectiveness": effect,
            "source_evidence_assessment": "Inconclusive", "historical_source": "Not established", "malicious_intent": "Not established",
            "additional_independent_evidence_required": True,
            "reason": "Virtual intervention evidence does not independently distinguish the retained malfunction/manipulation explanations or prove historical causation."},
        "recommended_next_actions": recommendations}
