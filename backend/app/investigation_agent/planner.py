"""Bounded, deterministic diagnostic selection; no experiment execution or AI."""
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
import json

from app.propagation.topology import downstream
from app.shadowtwin.experiments import Hypothesis, SUPPORTED_INTERVENTIONS
from app.shadowtwin.comparison import MAX_BRANCH_TICKS
from app.shadowtwin.foundation import MAX_ADVANCE_TICKS, MAX_TICKS
from .context import ObservableContext, observable_context, LOG_SIGNALS


EXPLANATIONS = {
    "use_redundant_solar": (("solar_fault", "Solar sensor malfunction"), ("solar_manipulation", "Solar measurement manipulation")),
    "restore_controller_policy": (("controller_fault", "Controller malfunction"), ("controller_manipulation", "Controller command manipulation")),
    "flush_communication": (("communication_buffer", "Stale communication buffers"), ("communication_manipulation", "Communication manipulation")),
}
PURPOSE = {
    "use_redundant_solar": "Test whether substituting the existing redundant solar measurement reduces the observed abnormal behavior.",
    "restore_controller_policy": "Test whether restoring the nominal controller policy reduces the observed command abnormality.",
    "flush_communication": "Test whether clearing buffered messages changes the observed communication abnormality.",
}
LIMITS = {
    "use_redundant_solar": "The redundant sensor is an alternative measurement, not an authenticated or guaranteed healthy reference.",
    "restore_controller_policy": "Nominal control still uses received inputs and applied configuration; upstream manipulation and inverter disturbances remain effective.",
    "flush_communication": "Communication flushing is temporary. It does not remove an ongoing attack and buffers may immediately refill.",
}
POLICY = [
    "Only current, component-linked residual exceedances or explicit abnormal observable log flags qualify a mechanism.",
    "Priority is lexicographic: number of distinct existing residual signals, then distinct log flags, then corroborating current accepted model groups.",
    "Repeated samples of the same signal do not increase priority; model scores, energy differences, hidden labels and downstream reachability are not ranking weights.",
    "Select the strongest eligible tier first, bounded by the planning budget. Equal priority is explicit ambiguity, never source confidence.",
    "Exact ties use intervention-identifier order solely for deterministic scheduling under a limited budget; deferred tied tests have equal evidential priority.",
]


@dataclass(frozen=True)
class PlanningBudget:
    max_candidates: int = 3
    max_experiments: int = 1
    duration_ticks: int = 20
    max_branch_ticks: int = MAX_BRANCH_TICKS

    def __post_init__(self):
        for key, upper in (("max_candidates", 3), ("max_experiments", 3),
                           ("duration_ticks", MAX_ADVANCE_TICKS), ("max_branch_ticks", MAX_BRANCH_TICKS)):
            value = getattr(self, key)
            lower = 1 if key == "duration_ticks" else 0
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{key} must be an integer from {lower} to {upper}")


def _capabilities(available):
    if available is None:
        available = SUPPORTED_INTERVENTIONS
    if isinstance(available, Mapping):
        entries = list(available)
        valid_pair = lambda name: available[name] == SUPPORTED_INTERVENTIONS.get(name)
    elif isinstance(available, Sequence) and not isinstance(available, (str, bytes)):
        entries = list(available)
        valid_pair = lambda name: True
    else:
        raise TypeError("Available interventions must be mechanism identifiers or the existing capability mapping")
    if len(entries) > 32 or any(not isinstance(name, str) or not name or len(name) > 100 for name in entries):
        raise ValueError("Provide at most 32 bounded capability identifiers")
    supported = sorted({name for name in entries if name in SUPPORTED_INTERVENTIONS and valid_pair(name)})
    return supported, sorted(set(entries) - set(supported))


def _candidate(name, context, budget):
    component = SUPPORTED_INTERVENTIONS[name]
    observations = [item for item in context.current_observations if component in item.components]
    if not observations:
        return None
    residuals = sorted({item.signal for item in observations if item.signal not in LOG_SIGNALS})
    logs = sorted({item.signal for item in observations if item.signal in LOG_SIGNALS})
    models = [name for name, nodes in (("phase1", context.phase1_components), ("stage_b", context.stage_b_components)) if component in nodes]
    priority = (len(residuals), len(logs), len(models))
    # Validate the request against the existing ShadowTwin type, without a snapshot.
    hypothesis = Hypothesis(f"diagnostic_{name}", component, PURPOSE[name], name, budget.duration_ticks)
    descriptions = []
    for item in observations:
        if item.signal in LOG_SIGNALS:
            descriptions.append(f"{item.signal} was recorded as {item.value} at tick {item.tick}")
        else:
            descriptions.append(f"{item.signal} was {item.value:g} {item.unit or ''} at tick {item.tick}, exceeding its supplied rule limit {item.threshold:g}")
    return {"intervention_id": name, "suspected_components": [component],
        "related_hypotheses": [{"hypothesis_id": ident, "explanation": label} for ident, label in EXPLANATIONS[name]],
        "observed_abnormalities": [asdict(item) for item in observations],
        "selection_reason": "; ".join(descriptions) + ". This supports a diagnostic test, not a confirmed source.",
        "diagnostic_purpose": PURPOSE[name],
        "priority_basis": {"distinct_residual_signals": residuals, "distinct_log_flags": logs, "current_model_corroboration": models},
        "hypothesis": {key: getattr(hypothesis, key) for key in ("hypothesis_id", "component", "mechanism", "intervention")},
        "duration_ticks": budget.duration_ticks, "estimated_branch_ticks": budget.duration_ticks * 2,
        "structural_downstream": downstream(component),
        "limitations": [LIMITS[name],
            "This intervention cannot independently distinguish accidental malfunction from malicious manipulation.",
            "Structural dependencies are possible downstream relationships, not proof of propagation.",
            "A fresh current-state checkpoint must be captured separately before execution; no snapshot was provided to this planner."],
        "_priority": priority}


def plan_investigation(observable_context_input, available_interventions=None, budget=None):
    """Return a JSON-compatible next-test plan, never execute it.

    Input is ObservableContext, or {'system_state': runtime.state(), 'incident':
    stored_incident}. Only the adapter's allowlisted values survive projection.
    An approved context is preferable at the Step 4.2 boundary. Neither interface
    accepts SimulationSnapshot, runtime, simulator objects or injection engines.
    """
    if type(observable_context_input) is ObservableContext:
        context = observable_context_input
    elif isinstance(observable_context_input, Mapping):
        context = observable_context(observable_context_input.get("system_state", {}), observable_context_input.get("incident"))
    else:
        raise TypeError("Planning accepts only an approved observable context or observable record mapping")
    if budget is None:
        budget = PlanningBudget()
    if type(budget) is not PlanningBudget:
        raise TypeError("budget must be PlanningBudget")
    available, unsupported = _capabilities(available_interventions)
    candidates = [item for name in available if (item := _candidate(name, context, budget)) is not None]
    candidates.sort(key=lambda item: (tuple(-value for value in item["_priority"]), item["intervention_id"]))
    supported_nodes = {SUPPORTED_INTERVENTIONS[name] for name in available}
    unsupported_nodes = sorted({node for item in context.current_observations for node in item.components if node not in supported_nodes})
    result = {"status": "insufficient_evidence", "reason": "No dated, current component-level abnormality supports a useful diagnostic intervention.",
        "context": {"incident_id": context.incident_id, "run_id": context.run_id, "current_tick": context.current_tick,
            "incident_observation_window": {"run_id": context.incident_run_id, "start_tick": context.incident_start_tick, "end_tick": context.incident_end_tick},
            "snapshot_available": context.snapshot_available, "snapshot_captured": False,
            "current_anomaly_status": context.current_status,
            "evidence_availability": {"current_observations": len(context.current_observations), "historical_observations": len(context.historical_observations)},
            "current_model_context": {"phase1_prediction": context.phase1_prediction, "stage_b_origin": context.stage_b_origin, "stage_b_nature": context.stage_b_nature}},
        "selected_experiments": [], "alternative_investigations": [], "equal_priority_groups": [],
        "uncertainty": {"limitations": list(context.limitations), "unsupported_interventions": unsupported,
            "unsupported_observed_components": unsupported_nodes, "missing_evidence": []},
        "budget": {**asdict(budget), "planned_branch_ticks": 0}, "selection_policy": list(POLICY)}
    if not context.current_observations:
        result["uncertainty"]["missing_evidence"].append("No relevant dated current residual exceedance or abnormal component log flag.")
    if context.current_tick is None:
        result["uncertainty"]["missing_evidence"].append("Current simulation tick is unavailable; historical evidence alone cannot justify a prospective test.")
    for priority in sorted({item["_priority"] for item in candidates}, reverse=True):
        group = [item["intervention_id"] for item in candidates if item["_priority"] == priority]
        if len(group) > 1:
            result["equal_priority_groups"].append(group)
    cost = 2 * budget.duration_ticks
    limited = budget.max_candidates == 0 or budget.max_experiments == 0 or cost > budget.max_branch_ticks
    horizon = context.current_tick is not None and context.current_tick + budget.duration_ticks > MAX_TICKS
    if limited or horizon:
        result.update(status="budget_exhausted", reason="No paired experiment fits the planning limits or existing simulation horizon.")
    elif context.current_tick is None or context.snapshot_available is False:
        if context.snapshot_available is False:
            result["reason"] = "The supplied current runtime is unavailable; a valid current-state capture is required before useful planning."
    elif not candidates and context.current_observations:
        result.update(status="unsupported", reason="Current abnormalities have no relevant supported intervention among the supplied capabilities.")
    elif not candidates and context.current_status == "normal":
        result.update(status="no_relevant_current_abnormality", reason="No relevant current abnormality was supplied. Historical incident evidence is not a replayable current condition.")
    elif candidates:
        result.update(status="ready", reason="Select the strongest evidence-supported diagnostic tier within budget; no historical source conclusion is made.")
        top = candidates[0]["_priority"]
        for item in candidates[:budget.max_candidates]:
            if item["_priority"] != top or len(result["selected_experiments"]) >= budget.max_experiments or result["budget"]["planned_branch_ticks"] + cost > budget.max_branch_ticks:
                continue
            result["selected_experiments"].append(item)
            result["budget"]["planned_branch_ticks"] += cost
    selected = {item["intervention_id"] for item in result["selected_experiments"]}
    for index, item in enumerate(candidates):
        if item["intervention_id"] in selected:
            continue
        if result["status"] != "ready":
            reason = result["reason"]
        elif index >= budget.max_candidates:
            reason = "Deferred by the candidate limit; no source exclusion is implied."
        elif candidates and item["_priority"] == candidates[0]["_priority"]:
            reason = "Equal evidential priority; deferred only by the planning budget and deterministic scheduling order."
        else:
            reason = "Lower lexicographic evidence priority under the documented policy; may be useful after the first test."
        result["alternative_investigations"].append({**item, "deferral_reason": reason,
            "possible_next_action": context.current_tick is not None and not horizon and context.snapshot_available is not False})
    for item in [*result["selected_experiments"], *result["alternative_investigations"]]:
        item.pop("_priority", None)
    # Identity depends only on projected plan data, never raw labels or wall time.
    encoded = json.dumps(result, sort_keys=True, allow_nan=False, separators=(",", ":"))
    return {"investigation_id": "plan-" + hashlib.sha256(encoded.encode()).hexdigest()[:16], **result}
