"""Observable residual comparisons; rankings are neither probabilities nor causes."""
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
import math

from app.explainability.evidence import SIGNAL_NODES
from app.localization.features import LocalizationFeatureExtractor
from app.propagation.investigation import SECURITY_LAYERS
from .experiments import Hypothesis, run_experiment
from .foundation import MAX_ADVANCE_TICKS, SimulationSnapshot


MAX_HYPOTHESES = 6
MAX_BRANCH_TICKS = 480  # Includes control and experimental work, before execution.
ABS_TOL = 1e-9
REL_TOL = 1e-6
ENERGY_BALANCE_TOL_KWH = 1e-8


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _close(a, b):
    return math.isclose(a, b, abs_tol=ABS_TOL, rel_tol=REL_TOL)


def _metrics(rows, config):
    """Reuse unchanged localization/detection residual rules, not another model.

    Means measure excess above the existing rule limit, not raw residual means.
    No emitted rule means the observed residual did not exceed its rule limit.
    The first SOC-step estimate is unavailable at an intermediate boundary.
    """
    extractor = LocalizationFeatureExtractor(config)
    result = {}
    for row in rows:
        for check in extractor.update(row).evidence:
            if not _number(check["value"]) or not _number(check["threshold"]) or check["threshold"] <= 0:
                raise ValueError("Residual rules must report finite values and positive limits")
            signal = check["signal"]
            item = result.setdefault(signal, {"mean_excess": 0.0, "normalized_excess": 0.0,
                "unit": check["unit"], "threshold": check["threshold"], "observation_ticks": []})
            excess = max(0.0, check["value"] - check["threshold"])
            item["mean_excess"] += excess
            item["normalized_excess"] += excess / check["threshold"]
            item["observation_ticks"].append(row["tick"])
    for signal, item in result.items():
        n = len(rows) - 1 if signal == "soc_step_residual" else len(rows)
        item["sample_count"] = n
        item["mean_excess"] /= max(1, n)
        item["normalized_excess"] /= max(1, n)
        if not _number(item["mean_excess"]) or not _number(item["normalized_excess"]):
            raise ValueError("Residual summaries must remain finite")
    return result


def _value(metrics, signal):
    return metrics.get(signal, {}).get("normalized_excess", 0.0)


def _pareto(items, signals):
    """Nondominated fronts, preserving equal profiles and incompatible trade-offs."""
    def dominates(a, b):
        pairs = [(_value(a["_after"], s), _value(b["_after"], s)) for s in signals]
        return all(x <= y or _close(x, y) for x, y in pairs) and any(x < y and not _close(x, y) for x, y in pairs)
    remaining, fronts = list(items), []
    while remaining:
        front = [a for a in remaining if not any(dominates(b, a) for b in remaining if b is not a)]
        if not front:
            # Approximate dominance can cycle at the tolerance boundary. Preserve
            # the entire remaining ambiguity group instead of looping or choosing.
            fronts.append(remaining)
            break
        fronts.append(front)
        remaining = [a for a in remaining if a not in front]
    return fronts


def _model_context(evidence):
    """Project official incident prediction fields; scores remain unweighted context."""
    phase1_groups = {"sensor": SECURITY_LAYERS["Sensor"], "communication": ["communication"],
                     "controller": ["controller"], "firmware": ["firmware"], "inverter": ["inverter"]}
    diagnosis = evidence.get("diagnosis") or {}
    security = evidence.get("security_attribution") or {}
    result = {}
    for name, record, label_key, score_key, candidates_key, candidate_key, groups in (
        ("phase1", diagnosis, "source", "confidence", "candidates", "source", phase1_groups),
        ("stage_b", security, "origin", "origin_confidence", "origin_candidates", "layer", SECURITY_LAYERS),
    ):
        if not isinstance(record, Mapping):
            continue
        label = record.get(label_key)
        if label not in (*groups, "unknown", "Unknown", "normal", "Normal", None):
            label = None
        available = record.get("source_model_available") is True if name == "phase1" else record.get("available") is True
        candidates = []
        raw_candidates = record.get(candidates_key)
        if isinstance(raw_candidates, list):
            for candidate in raw_candidates[:10]:
                if (isinstance(candidate, Mapping) and isinstance(candidate.get(candidate_key), str)
                        and candidate[candidate_key] in groups and _number(candidate.get("confidence"))):
                    score = candidate["confidence"]
                    if 0 <= score <= 1:
                        candidates.append({"label": candidate[candidate_key], "model_score": score})
        score = record.get(score_key)
        result[name] = {"prediction": label, "available": available,
            "model_score": score if _number(score) and 0 <= score <= 1 else None,
            "candidate_scores": candidates,
            "interpretation": "Reported model scores; not probabilities of historical source correctness or ranking weights.",
            "candidate_components": list(groups.get(label, [])) if available else []}
        if name == "stage_b":
            nature = record.get("nature", record.get("nature_verdict"))
            result[name]["nature"] = nature if nature in ("Normal", "Accidental fault", "Cyber attack", "Undetermined") else None
    return result


def _recorded_evidence(evidence, start_tick):
    records = evidence.get("evidence", [])
    if not isinstance(records, list) or len(records) > 256:
        raise ValueError("observable_evidence.evidence must contain at most 256 records")
    result = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        signal, tick = record.get("signal"), record.get("tick")
        value, threshold = record.get("value"), record.get("threshold")
        if (isinstance(signal, str) and signal in SIGNAL_NODES and type(tick) is int and 0 <= tick < start_tick
                and _number(value) and _number(threshold) and threshold > 0 and value > threshold
                and record.get("id") == f"t{tick}:{signal}"):
            result.append({"id": record["id"], "tick": tick, "signal": signal,
                           "value": value, "threshold": threshold})
    return result


def compare_hypotheses(snapshot, hypotheses, duration_ticks, observable_evidence=None, *, comparison_id="comparison"):
    """Run a bounded batch from one checkpoint; return JSON-compatible observations.

    Pareto comparisons use the SAME residual axes, each normalized only by its
    existing physical rule threshold. No energy, ML score or source label is a
    ranking weight. A unique ranking concerns prospective relative evidence only.
    """
    if not isinstance(snapshot, SimulationSnapshot):
        raise TypeError("snapshot must be a SimulationSnapshot")
    if not isinstance(hypotheses, Sequence) or not 2 <= len(hypotheses) <= MAX_HYPOTHESES or any(not isinstance(h, Hypothesis) for h in hypotheses):
        raise ValueError(f"Supply 2 to {MAX_HYPOTHESES} explicit Hypothesis objects")
    if type(duration_ticks) is not int or not 1 <= duration_ticks <= MAX_ADVANCE_TICKS:
        raise ValueError("Invalid common experiment duration")
    if len(hypotheses) * duration_ticks * 2 > MAX_BRANCH_TICKS:
        raise ValueError("Batch exceeds the total control/experimental tick budget")
    if snapshot.next_tick + duration_ticks > snapshot._max_tick:
        raise ValueError("Batch exceeds the captured simulation horizon")
    if not isinstance(comparison_id, str) or not comparison_id.strip():
        raise ValueError("comparison_id must be a nonempty string")
    if len({h.hypothesis_id for h in hypotheses}) != len(hypotheses):
        raise ValueError("Hypothesis identifiers must be unique")
    if len({h.checkpoint_id for h in hypotheses}) != 1:
        raise ValueError("All hypothesis checkpoint identifiers must refer to the supplied checkpoint")
    evidence = {} if observable_evidence is None else observable_evidence
    if not isinstance(evidence, Mapping):
        raise ValueError("observable_evidence must be an incident-evidence mapping")
    start = snapshot.next_tick
    context = _model_context(evidence)
    records = _recorded_evidence(evidence, start)
    items = []
    # Only intended physical configuration is read, never schedules, seed or labels.
    config = snapshot._simulator.config
    for hypothesis in sorted(hypotheses, key=lambda h: h.hypothesis_id):
        item = {"hypothesis_id": hypothesis.hypothesis_id, "suspected_component": hypothesis.component,
            "proposed_mechanism": hypothesis.mechanism, "intervention": hypothesis.intervention,
            "experiment_status": None, "ranking_position": None, "intervention_rank": None,
            "eligible_for_ranking": False, "exclusion_reason": None,
            "evidence_assessment": "Inconclusive", "intervention_outcome": "Not evaluated",
            "delivered_energy_difference_kwh": None, "physical_observations": {},
            "energy_balance_residuals_kwh": {},
            "relevant_abnormalities": [], "remaining_abnormalities": [], "new_or_worsened_abnormalities": [],
            "model_agreement": {}, "recorded_evidence_ids": [r["id"] for r in records if hypothesis.component in SIGNAL_NODES[r["signal"]]],
            "explanation": "", "warnings": [], "experiment": None}
        items.append(item)
        try:
            experiment = run_experiment(snapshot, replace(hypothesis, duration_ticks=duration_ticks),
                                        experiment_id=f"{comparison_id}:{hypothesis.hypothesis_id}")
        except Exception as error:
            item.update(experiment_status="invalid" if isinstance(error, (ValueError, TypeError)) else "failed",
                        exclusion_reason=f"Experiment could not run ({type(error).__name__}).")
            continue
        item.update(experiment_status=experiment.status, warnings=list(experiment.warnings), experiment=asdict(experiment))
        if experiment.status != "completed":
            item["exclusion_reason"] = experiment.reason or "Experiment did not complete."
            item["evidence_assessment"] = "Unsupported experiment" if experiment.status == "unsupported" else "Inconclusive"
            continue
        a, b = experiment.control_telemetry, experiment.experimental_telemetry
        if (experiment.start_tick != start or experiment.end_tick != start + duration_ticks
                or len(a) != duration_ticks or len(b) != duration_ticks
                or any(x.get("tick") != tick or y.get("tick") != tick or x.get("elapsed_seconds") != y.get("elapsed_seconds")
                       for tick, (x, y) in enumerate(zip(a, b), start))):
            item["exclusion_reason"] = "Missing, incomplete or misaligned observations."
            continue
        try:
            before, after = _metrics(a, config), _metrics(b, config)
        except (KeyError, TypeError, ValueError):
            item["exclusion_reason"] = "Insufficient finite observable measurements for existing residual checks."
            continue
        item["_before"], item["_after"] = before, after
        signals = sorted(before.keys() | after.keys())
        for signal in signals:
            x, y = _value(before, signal), _value(after, signal)
            template = before.get(signal, after.get(signal))
            reduction = (x - y) / x if x > ABS_TOL else None
            item["physical_observations"][signal] = {"unit": template["unit"], "existing_rule_threshold": template["threshold"],
                "control_mean_excess": before.get(signal, {}).get("mean_excess", 0.0),
                "experimental_mean_excess": after.get(signal, {}).get("mean_excess", 0.0),
                "control_normalized_excess": x, "experimental_normalized_excess": y,
                "relative_reduction": reduction if _number(reduction) else None,
                "control_observation_ticks": before.get(signal, {}).get("observation_ticks", []),
                "experimental_observation_ticks": after.get(signal, {}).get("observation_ticks", [])}
            if x > ABS_TOL and hypothesis.component in SIGNAL_NODES.get(signal, []):
                item["relevant_abnormalities"].append(signal)
            if y > ABS_TOL:
                item["remaining_abnormalities"].append(signal)
            if y > x and not _close(x, y):
                item["new_or_worsened_abnormalities"].append(signal)
        delta = experiment.energy.get("experimental_minus_control", {}).get("delivered_kwh")
        item["delivered_energy_difference_kwh"] = delta if _number(delta) else None
        inconsistent_energy = False
        for name in ("control", "experimental"):
            ledger = experiment.energy.get(name, {})
            item["energy_balance_residuals_kwh"][name] = {}
            for key in ("energy_balance_residual_kwh", "renewable_energy_balance_residual_kwh"):
                value = ledger.get(key)
                item["energy_balance_residuals_kwh"][name][key] = value if _number(value) else None
                if _number(value) and abs(value) > ENERGY_BALANCE_TOL_KWH:
                    inconsistent_energy = True
        improved = [s for s in item["relevant_abnormalities"] if _value(after, s) < _value(before, s) and not _close(_value(after, s), _value(before, s))]
        item["_improved"] = improved
        for name, model in context.items():
            components = model["candidate_components"]
            item["model_agreement"][name] = "unknown" if not components else ("same_candidate_group" if hypothesis.component in components else "different_candidate_group")
        if _number(delta) and delta < -ABS_TOL:
            outcome = "Worsened delivered energy" if not improved else "Relevant residual reduction with worsened delivered energy"
        elif improved:
            outcome = "Mixed effects" if item["new_or_worsened_abnormalities"] else "Relevant symptoms reduced"
        else:
            outcome = "Energy gain only" if _number(delta) and delta > ABS_TOL else "No relevant symptom improvement"
        item["intervention_outcome"] = outcome
        item["evidence_assessment"] = "Partial evidence support" if improved else ("Weak evidence support" if item["relevant_abnormalities"] else "Inconclusive")
        if inconsistent_energy:
            item["exclusion_reason"] = "Existing energy-ledger residuals exceed the conservation tolerance; numerical ranking is not justified."
            item["evidence_assessment"] = "Inconclusive"
        elif experiment.external_conditions_matched is not True or experiment.random_states_matched is not True:
            item["exclusion_reason"] = "Unmatched external conditions or random streams; numerical ranking is not justified."
            item["evidence_assessment"] = "Inconclusive"
        else:
            item["eligible_for_ranking"] = True
    valid = [item for item in items if item["eligible_for_ranking"]]
    if len(valid) > 1 and any(item["experiment"]["control_telemetry"] != valid[0]["experiment"]["control_telemetry"] for item in valid[1:]):
        for item in valid:
            item.update(eligible_for_ranking=False, evidence_assessment="Inconclusive", exclusion_reason="Control branches differ; experiments are not comparable.")
        valid = []
    signals = sorted({s for item in valid for s in item["_before"]} | {s for item in valid for s in item["_after"]})
    active = [s for s in signals if valid and _value(valid[0]["_before"], s) > ABS_TOL]
    fronts = _pareto(valid, signals) if len(valid) >= 2 and active else []
    ranking = []
    source_support_available = any(item.get("_improved") for item in valid)
    for position, front in enumerate(fronts, 1):
        equivalent = all(all(_close(_value(item["_after"], s), _value(front[0]["_after"], s)) for s in signals) for item in front)
        ranking.append({"position": position, "hypothesis_ids": [item["hypothesis_id"] for item in front],
                        "relationship": "equivalent" if len(front) > 1 and equivalent else ("trade_off" if len(front) > 1 else "distinguishable")})
        for item in front:
            item["ranking_position"] = position if source_support_available else None
            item["intervention_rank"] = position
    top = fronts[0] if fronts else []
    strongest = top[0] if len(top) == 1 else None
    distinguishable = bool(strongest and strongest.get("_improved") and strongest["experiment"]["sustained"]
        and not strongest["new_or_worsened_abnormalities"]
        and "different_candidate_group" not in strongest["model_agreement"].values())
    if distinguishable:
        strongest["evidence_assessment"] = "Stronger relative evidence support"
    reasons = []
    if len(valid) < 2:
        reasons.append("Fewer than two valid comparable experiments; untested alternatives are not ruled out.")
    elif not active:
        reasons.append("No above-threshold control abnormality was measurable using the existing residual rules.")
    elif not source_support_available:
        reasons.append("No intervention reduced a relevant observed abnormality; source support is insufficient.")
    if len(top) > 1:
        reasons.append("Top residual profiles are equivalent or have incompatible trade-offs; no tie-break is justified.")
    if strongest and not distinguishable:
        reasons.append("The best residual profile lacks sustained relevant improvement, has contradictory abnormalities, or conflicts with independent model predictions.")
    for item in items:
        if item["exclusion_reason"]:
            item["explanation"] = item["exclusion_reason"] + " No source ranking is inferred from this missing experiment."
        elif not item["relevant_abnormalities"]:
            item["explanation"] = "No relevant above-threshold abnormality was observed for this hypothesis; source support is insufficient."
        else:
            parts = []
            for signal in item["relevant_abnormalities"]:
                observation = item["physical_observations"][signal]
                parts.append(f"{signal}: mean excess above its existing rule limit changed from {observation['control_mean_excess']:.6g} to {observation['experimental_mean_excess']:.6g} {observation['unit']}")
            item["explanation"] = "; ".join(parts) + "."
        delta = item["delivered_energy_difference_kwh"]
        if delta is not None:
            item["explanation"] += f" Delivered-energy difference is {delta:+.6g} kWh (experimental minus control)."
        if item["new_or_worsened_abnormalities"]:
            item["explanation"] += " Other abnormalities worsened: " + ", ".join(item["new_or_worsened_abnormalities"]) + "."
        if item["experiment"] and item["experiment"].get("intervention_status") == "applied_once":
            item["explanation"] += " The intervention was temporary, not sustained containment."
        if "different_candidate_group" in item["model_agreement"].values():
            item["explanation"] += " An independent model prediction points to a different candidate group; this conflict remains unresolved."
        if item["recorded_evidence_ids"]:
            item["explanation"] += " Earlier recorded observations linked: " + ", ".join(item["recorded_evidence_ids"]) + "."
        item["explanation"] += " This is prospective intervention evidence, not proof of the historical source or malicious intent."
        for key in ("_before", "_after", "_improved"):
            item.pop(key, None)
    return {"comparison_id": comparison_id, "snapshot_id": hypotheses[0].checkpoint_id,
        "start_tick": start, "end_tick": start + duration_ticks, "hypothesis_count": len(items),
        "status": "Ranked prospective evidence" if distinguishable else "Inconclusive",
        "historical_source": "Not established", "inconclusive_reasons": reasons,
        "hypothesis_ranking": ranking if source_support_available else [], "intervention_ranking": ranking,
        "tied_or_tradeoff_groups": [r["hypothesis_ids"] for r in ranking if len(r["hypothesis_ids"]) > 1],
        "hypotheses": items, "independent_model_evidence": context, "recorded_evidence": records,
        "limitations": ["Ranks are Pareto fronts of observed residual burdens, not source probabilities.",
            "Energy differences and model scores never contribute ranking weights.",
            "Equal fronts can represent equivalent outcomes or incompatible trade-offs; no arbitrary tie-break is used.",
            "Fewer than two comparable experiments or no relevant abnormalities yields no ranking.",
            "Only current-checkpoint prospective experiments are supported; historical causation and incident nature remain unproven.",
            "The first SOC-step residual at an intermediate boundary and initialized absolute SOC estimates are unavailable.",
            "Grid import/export remain unavailable; untested or unsupported alternatives are not ruled out."]}
