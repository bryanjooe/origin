"""Bounded manual orchestration above the existing planner and ShadowTwin engine."""
from dataclasses import dataclass, replace

from app.shadowtwin import SimulationSnapshot, Hypothesis
from app.shadowtwin.experiments import ExperimentResult, run_experiment
from app.shadowtwin.comparison import assess_experiments
from .context import ObservableContext, LOG_SIGNALS, observable_context
from .planner import PlanningBudget, plan_investigation
from .fusion import fusion_report, experiment_observations, observation_groups


@dataclass(frozen=True)
class SnapshotReference:
    """Caller-bound provenance. Prefer the atomic capture helper below.

    A bare SimulationSnapshot has no run ID and is deliberately not accepted by
    the orchestrator. Manually constructed references require trusted provenance.
    """
    snapshot: SimulationSnapshot
    run_id: str
    reference_id: str

    def __post_init__(self):
        if type(self.snapshot) is not SimulationSnapshot:
            raise TypeError("Use an existing independent SimulationSnapshot")
        if any(not isinstance(value, str) or not value.strip() or len(value) > 256 for value in (self.run_id, self.reference_id)):
            raise ValueError("Run and snapshot reference identifiers are required")

    @property
    def max_tick(self):
        # Execution constraint only; no labels, schedules, seed or private
        # simulator fields are read for planning/fusion.
        return self.snapshot._max_tick


async def capture_investigation_inputs(runtime, incident_id=None):
    """Explicit internal helper, not a trigger/endpoint. Read and clone under lock."""
    async with runtime.lock:
        incident = runtime.store.incident(incident_id) if incident_id is not None else None
        if incident_id is not None and incident is None:
            raise KeyError("Incident not found")
        context = observable_context(runtime.state(), incident)
        snapshot = runtime._shadow_snapshot_locked()
        return context, SnapshotReference(snapshot, runtime.run_id, f"{runtime.run_id}:{snapshot.next_tick}")


def _comparison_context(context):
    # Current accepted model groups only. Original model outputs remain in the
    # report; historical model context is not relabeled as current evidence.
    return {"diagnosis": {"source": context.phase1_prediction, "source_model_available": context.phase1_prediction is not None},
        "security_attribution": {"origin": context.stage_b_origin, "nature_verdict": context.stage_b_nature,
                                 "available": context.stage_b_origin is not None}}


def _remaining_context(context, item, experiment):
    if not item.get("eligible_for_ranking"):
        return context
    remaining = set(item.get("remaining_abnormalities", []))
    retained = []
    for observation in context.current_observations:
        if observation.signal not in LOG_SIGNALS:
            if observation.signal in remaining:
                retained.append(observation)
        else:
            # Keep an initial log target unless actual virtual rows show that
            # specific flag was observed and no longer abnormal throughout.
            values = [(row.get("security_telemetry") or {}).get(observation.signal) for row in experiment.experimental_telemetry]
            abnormal = LOG_SIGNALS[observation.signal][0]
            if not values or any(type(value) is not bool or value == abnormal for value in values):
                retained.append(observation)
    return replace(context, current_observations=tuple(retained))


def run_autonomous_investigation(context, snapshot, budget=None, *, available_interventions=None, progress=None):
    """Execute at most three distinct paired tests from the same detached state.

    Result-dependent filtering retains original dated targets only when they
    remain unresolved in the virtual outcome. No future sample is backdated or
    presented as live telemetry. All priority choices call the Step 4.1 planner.
    """
    if type(context) is not ObservableContext or type(snapshot) is not SnapshotReference:
        raise TypeError("Use an approved ObservableContext and bound SnapshotReference")
    if context.run_id != snapshot.run_id or context.current_tick != snapshot.snapshot.next_tick:
        raise ValueError("Observable context and snapshot run/tick do not match")
    budget = PlanningBudget(max_experiments=3) if budget is None else budget
    if type(budget) is not PlanningBudget:
        raise TypeError("budget must be PlanningBudget")
    def emit(stage, **details):
        if progress is not None:
            progress({"stage":stage, **details})
    emit("reviewing_evidence")
    initial_plan = plan_investigation(context, available_interventions, replace(budget, max_experiments=min(1, budget.max_experiments)))
    if context.current_tick + budget.duration_ticks > snapshot.max_tick:
        initial_plan = {**initial_plan, "status":"budget_exhausted", "reason":"The requested experiment exceeds the supplied checkpoint horizon."}
    report = {"investigation_id": initial_plan["investigation_id"], "incident_id": context.incident_id,
        "run_id": snapshot.run_id, "snapshot_reference": snapshot.reference_id, "snapshot_tick": snapshot.snapshot.next_tick,
        "status": initial_plan["status"], "stopping_reason": initial_plan["status"], "stopping_explanation": initial_plan["reason"],
        "executed_experiments": 0, "attempted_experiments": 0, "branch_ticks_charged": 0,
        "budget": {"max_candidates":budget.max_candidates,"max_experiments":budget.max_experiments,
                   "duration_ticks":budget.duration_ticks,"max_branch_ticks":budget.max_branch_ticks},
        "steps": [], "initial_plan": initial_plan, "comparison": None,
        "technical_metadata": {"isolation": "Existing independent ShadowTwin control/intervention forks; no live state or database writes.",
            "comparison_work": "Cached-result assessment only; no experiment is rerun for ranking.",
            "work_accounting": "Each attempt reserves the full paired duration, including failed or unsupported attempts."
        }}
    cache, hypotheses = {}, []
    attempted = set()
    current = context
    plan = initial_plan
    # Only initially admitted evidence-supported mechanisms can enter this batch.
    candidates = [*initial_plan["selected_experiments"], *initial_plan["alternative_investigations"]]
    eligible_names = list(dict.fromkeys(item["intervention_id"] for item in candidates))
    admitted = eligible_names[:budget.max_candidates]
    comparison = None
    while plan["status"] == "ready":
        if not plan["selected_experiments"]:
            report.update(status="partial", stopping_reason="no_useful_current_evidence", stopping_explanation="The planner returned no executable selected test.")
            break
        choice = plan["selected_experiments"][0]
        mechanism = choice["intervention_id"]
        cost = 2 * budget.duration_ticks
        if mechanism in attempted:
            report.update(status="partial", stopping_reason="repeated_experiment_prevented", stopping_explanation="An equivalent intervention was already attempted; no retry was executed.")
            break
        if mechanism not in admitted or len(attempted) >= min(budget.max_experiments, budget.max_candidates) or report["branch_ticks_charged"] + cost > budget.max_branch_ticks:
            report.update(status="budget_exhausted", stopping_reason="budget_exhausted", stopping_explanation="Further justified work exceeds the investigation budget.")
            break
        attempted.add(mechanism)
        report["attempted_experiments"] += 1
        report["branch_ticks_charged"] += cost
        emit("selecting_experiment", intervention_id=mechanism, step=len(attempted), reason=choice["selection_reason"])
        hypothesis = Hypothesis(**choice["hypothesis"], duration_ticks=budget.duration_ticks, checkpoint_id=snapshot.reference_id)
        experiment_id = f"{report['investigation_id']}:step-{len(attempted)}"
        emit("running_shadowtwin", intervention_id=mechanism, step=len(attempted))
        try:
            experiment = run_experiment(snapshot.snapshot, hypothesis, experiment_id=experiment_id)
            if not isinstance(experiment, ExperimentResult):
                raise TypeError("Experiment result contract violated")
        except Exception as error:
            experiment = ExperimentResult(experiment_id, hypothesis.hypothesis_id, hypothesis.component, hypothesis.mechanism,
                hypothesis.intervention, hypothesis.checkpoint_id, status="invalid" if isinstance(error,(ValueError,TypeError)) else "failed",
                reason=f"Experiment did not complete ({type(error).__name__}); no measurements are inferred.")
        emit("evaluating_results", intervention_id=mechanism, step=len(attempted))
        cache[hypothesis.hypothesis_id] = experiment
        hypotheses.append(hypothesis)
        try:
            comparison = assess_experiments(snapshot.snapshot, hypotheses, cache, budget.duration_ticks,
                _comparison_context(context), comparison_id=report["investigation_id"])
        except (ValueError, TypeError) as error:
            # Identity-invalid results are recorded as invalid, never reused as
            # measurements. The selected attempt remains charged to the budget.
            experiment = ExperimentResult(experiment_id, hypothesis.hypothesis_id, hypothesis.component, hypothesis.mechanism,
                hypothesis.intervention, hypothesis.checkpoint_id, status="invalid", reason=f"Result validation failed ({type(error).__name__}).")
            cache[hypothesis.hypothesis_id] = experiment
            comparison = assess_experiments(snapshot.snapshot, hypotheses, cache, budget.duration_ticks,
                _comparison_context(context), comparison_id=report["investigation_id"])
        if experiment.status == "completed":
            report["executed_experiments"] += 1
        item = next(item for item in comparison["hypotheses"] if item["hypothesis_id"] == hypothesis.hypothesis_id)
        step = {"step":len(attempted),"experiment_id":experiment_id,"intervention_id":mechanism,
            "related_hypotheses":choice["related_hypotheses"],"selection_reason":choice["selection_reason"],
            "relevant_evidence":observation_groups(current.current_observations),
            "start_tick":experiment.start_tick,"end_tick":experiment.end_tick,"execution_status":experiment.status,
            "duration_ticks":budget.duration_ticks,"branch_ticks_charged":cost,
            "intervention_outcome":item["intervention_outcome"],"physical_observations":item["physical_observations"],
            "delivered_energy_difference_kwh":item["delivered_energy_difference_kwh"],
            "comparable":item["eligible_for_ranking"],"exclusion_reason":item["exclusion_reason"],
            "limitations":list(dict.fromkeys([*choice["limitations"],*experiment.limitations,*experiment.warnings])),
            **experiment_observations(experiment)}
        report["steps"].append(step)
        emit("checking_uncertainty", intervention_id=mechanism, step=len(attempted))
        current = _remaining_context(current, item, experiment)
        remaining_names = [name for name in eligible_names if name not in attempted]
        # Ask the same planner again; do not advance through the original list.
        next_plan = plan_investigation(current, remaining_names, replace(budget,max_experiments=1,
            max_branch_ticks=max(0,budget.max_branch_ticks-report["branch_ticks_charged"])))
        justified = bool(next_plan["selected_experiments"])
        # A budget-exhausted plan retains justified candidates as alternatives.
        needs_work = justified or (next_plan["status"] == "budget_exhausted" and bool(next_plan["alternative_investigations"]))
        eligible = item["eligible_for_ranking"]
        no_abnormality = eligible and not any(value["control_normalized_excess"] > 0 for value in item["physical_observations"].values())
        if no_abnormality:
            reason, status, detail = "no_relevant_comparison_abnormality", "completed", "No relevant above-rule abnormality was measurable in the prospective comparison window; old incident conditions were not replayed."
        elif not needs_work:
            if not eligible:
                reason, status, detail = "experiment_failure_or_incompatible_results", "partial" if any(item["eligible_for_ranking"] for item in comparison["hypotheses"]) else "failed", "No valid distinct supported alternative remains after the failed, unsupported or incomparable attempt."
            elif item["intervention_outcome"] == "Relevant symptoms reduced" and not item["remaining_abnormalities"]:
                reason, status, detail = "sufficient_intervention_evidence", "completed", "Relevant virtual abnormalities were reduced and no further supported target is justified. Historical source and malicious intent remain unresolved."
            else:
                reason, status, detail = "no_additional_distinguishing_experiment", "completed", "Remaining explanations cannot be distinguished by another untried supported mechanism justified by the observed targets."
        elif (justified and next_plan["selected_experiments"][0]["intervention_id"] not in admitted) or len(attempted) >= min(budget.max_experiments,budget.max_candidates) or report["branch_ticks_charged"]+cost>budget.max_branch_ticks:
            reason, status, detail = "budget_exhausted", "budget_exhausted", "Another evidence-supported test remains, but it does not fit the remaining investigation budget."
        else:
            reason, status, detail = "continue_with_supported_alternative", "running", "A different original observed target remains unresolved in the virtual outcome; the planner selected another distinct mechanism." if eligible else "A distinct originally supported alternative remains after an invalid or failed attempt; no retry is made."
        step["decision_afterward"] = {"action": "continue" if status == "running" else "stop", "reason":reason,"explanation":detail,
            "next_intervention": next_plan["selected_experiments"][0]["intervention_id"] if justified and status == "running" else None,
            "remaining_original_targets":sorted({observation.signal for observation in current.current_observations})}
        emit("decision_recorded", completed_step=step)
        report.update(status=status,stopping_reason=reason,stopping_explanation=detail)
        if status != "running":
            break
        plan = next_plan
    if comparison:
        # Keep the final shared assessment's comparability decisions authoritative.
        final_items = {item["hypothesis_id"]:item for item in comparison["hypotheses"]}
        for step, hypothesis in zip(report["steps"], hypotheses):
            item=final_items[hypothesis.hypothesis_id]
            step["comparable"]=item["eligible_for_ranking"]
            step["exclusion_reason"]=item["exclusion_reason"]
        report["comparison"] = {key: value for key,value in comparison.items() if key != "hypotheses"}
        report["comparison"]["hypotheses"] = [{key:value for key,value in item.items() if key != "experiment"} for item in comparison["hypotheses"]]
    if report["status"] == "completed" and comparison and any(not item["eligible_for_ranking"] for item in comparison["hypotheses"]):
        report["status"] = "partial"
    emit("generating_report")
    report.update(fusion_report(context,report["steps"],comparison,initial_plan))
    return report
