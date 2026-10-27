# Autonomous investigation planning — Phase 4.1

The planner remains read-only. Phase 4.2 now adds a separate optional execution
layer; see [EXECUTION.md](EXECUTION.md) for its manual internal interface and limits.

`plan_investigation` is an internal, synchronous, read-only planning function.
It neither captures snapshots nor executes ShadowTwin or alters simulator state.
No endpoint, runtime integration, frontend, model, or dependency is added.

## Boundary and use

```python
from app.investigation_agent import observable_context, plan_investigation, PlanningBudget

# A future integration must obtain these existing read-only records together,
# under the runtime's existing lock. Do not pass a runtime or SimulationSnapshot.
context = observable_context(system_state_record, stored_incident_record)
plan = plan_investigation(context, budget=PlanningBudget())
```

Alternatively pass `{'system_state': state_record, 'incident': incident_record}`.
Unknown fields at every projected level are ignored, not copied. The approved
context is frozen and contains only identifiers, timing, validated observations,
accepted current model groups, limitation codes, and approved original model
records for reporting. Those additional reporting records do not influence the
planner's selection rules. Simulator/checkpoint objects
are rejected. The planner has no runtime or snapshot reference.

`current_tick` means the existing runtime's `next_tick`. A current observation must
be dated `next_tick - 1`. Undated, older, future, and non-finite current residuals
cannot justify a test. Same-run incident evidence at exactly that tick may be used;
other evidence is historical context only. Different runs have independent tick
counters. Existing `first_observed_tick` and `last_alert_tick` describe the incident
window, not the current snapshot. Missing run identity prevents incident evidence
and Stage B records from being assumed current; independently dated current
anomaly/log records can still inform planning.

Residual records reuse `explainability.evidence.SIGNAL_NODES` and their supplied
existing thresholds. No thresholds or residuals are calculated here. Boolean
security-log flags reuse existing observable log semantics: sensor disagreement,
controller-policy inconsistency, duplicate/out-of-order messages, and configuration
mismatch. Repeated samples do not count as independent priority signals.

## Selection policy

Only mechanisms with current component-linked abnormal observations are eligible.
Official model predictions alone, old incident symptoms, global anomaly scores,
energy shortfalls and downstream reachability cannot invent a candidate.

Eligible mechanisms are ordered lexicographically by:

1. Number of **distinct existing residual rules** that support the component.
2. Number of distinct explicitly abnormal observable security-log flags.
3. Number of corroborating, current accepted Phase 1 / Stage B candidate groups.

These are test-selection rules, not likelihoods, calibrated probabilities,
expected information-gain estimates or new source-ranking algorithms. Model scores
are not used. A current `Sensor` prediction retains its multi-sensor group; local
observations, not an arbitrary sensor choice, justify the solar intervention.
Unknown/Undetermined predictions do not block direct observable evidence.

Only the strongest tier is proposed now. Lower-priority mechanisms are deferred
as possible next actions, not executed. Exact ties are reported in
`equal_priority_groups`; identifier order is an explicitly operational tie-break
under a limited budget, not evidence of source preference. Increase the experiment
budget to retain several tied tests. Existing ShadowTwin Pareto ranking is untouched.

The default budget admits up to 3 relevant candidate mechanisms, selects **1 next
paired diagnostic experiment**, and uses 20 ticks per branch. At most 3 experiments
can be planned. Each mechanism costs `2 * duration_ticks` (original and intervention),
bounded by ShadowTwin's 480 branch-tick batch limit and 10000-tick global horizon.
`max_candidates` limits admission to the current batch after evidence ordering;
non-admitted mechanisms may still be listed as deferred future actions. Duration
must respect the existing 1–1000 advance limit. There are no iterative loops.

Mechanisms and component compatibility come from
`shadowtwin.experiments.SUPPORTED_INTERVENTIONS`. Each selected mechanism has one
`hypothesis` request template compatible with the existing `Hypothesis` type,
while `related_hypotheses` retains both existing possible explanations:

- `use_redundant_solar`: malfunction / measurement manipulation.
- `restore_controller_policy`: malfunction / command manipulation.
- `flush_communication`: stale buffers / communication manipulation.

The request template is not an executed experiment or a captured checkpoint.
Phase 4.2 must capture fresh state and revalidate budgets and runtime horizon.
It must not directly submit a single planned mechanism to the comparison API's
multi-hypothesis batch contract. The existing single paired `run_experiment`
interface is the compatible execution primitive; execution is not implemented here.

## Output and uncertainty

JSON-compatible output contains deterministic `investigation_id`, `context`,
`selected_experiments`, `alternative_investigations`, `equal_priority_groups`,
`uncertainty`, `budget`, `selection_policy`, `status`, and `reason`.
Every selected test includes actual projected observations, its selection reason,
purpose, related explanations, known limitations, and structural downstream nodes.
Dependencies are explanatory possibilities, never proof of transmission or a
priority weight. IDs for unsaved current checks are `null`, not fabricated records.

Statuses:

- `ready`: one or more justified tests fit the budget.
- `insufficient_evidence`: insufficient dated current local evidence, missing
  current tick, or explicitly unavailable current state.
- `no_relevant_current_abnormality`: the current dated detector reports normal
  and no relevant current local abnormality was supplied.
- `unsupported`: current abnormalities have no relevant available mechanism.
- `budget_exhausted`: no test fits the stated work/experiment/candidate/horizon limits.

`historical_incident_current_state_only` warns that older evidence is not a replay
of the current state. Historical evidence alone cannot create a ready plan. Even
useful intervention effects cannot identify historical origin or malicious intent.
Communication flushing is temporary and does not remove an ongoing attack.
Models, ambiguity, missing evidence and unsupported components remain explicit.

The plan identity hashes only the approved JSON output: equal observations and
capabilities produce the same plan, independent of hidden injection labels,
input order, wall-clock time, or mutable simulator internals.
