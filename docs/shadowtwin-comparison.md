# Phase 3 Step 3.3 — Transparent hypothesis comparison

Completed as an internal Python service. No frontend integration, public API,
autonomous hypothesis selection, AI model, model training or simulation change
is introduced. Earlier uncommitted fault-fix and Step 3.1/3.2 work is preserved.

## Interface and reuse

```python
from app.shadowtwin import Hypothesis, compare_hypotheses

snapshot = await runtime.shadow_snapshot(at_tick=100)
hypotheses = [
    Hypothesis("H1", "solar_sensor", "measurement inconsistency", "use_redundant_solar"),
    Hypothesis("H2", "controller", "command inconsistency", "restore_controller_policy"),
    Hypothesis("H3", "communication", "transport inconsistency", "flush_communication"),
]
result = compare_hypotheses(snapshot, hypotheses, duration_ticks=20,
                            observable_evidence=incident_report,
                            comparison_id="comparison-1")
```

`observable_evidence` is optional. When provided, use the existing incident
response's `evidence`, `diagnosis` and `security_attribution` fields. Do not pass
simulator metadata as investigation evidence. Unknown extra fields are ignored
and never returned. Model predictions are projected separately; Unknown,
Undetermined and unavailable model states remain valid.

The comparison calls Step 3.2 `run_experiment()` for every explicit hypothesis.
All calls receive the SAME original `SimulationSnapshot` and common duration;
the hypotheses' individual duration fields are overridden in copies, not mutated.
Control observations must match across experiments. Step 3.1 supplies independent
branches, six preserved RNG states and private energy ledgers. No second engine,
cloning implementation, intervention mechanism or runtime manager is added.

The result is JSON-compatible and includes actual Step 3.2 results, experimental
ticks, evidence summaries, model context, per-hypothesis explanations, independent
intervention outcomes, source-support categories, partial rankings and explicit
Inconclusive reasons. Snapshot identifiers remain caller labels; the supplied
snapshot object is the actual shared checkpoint reference.

## Residual measurements

The comparison reuses the UNCHANGED `LocalizationFeatureExtractor`, including its
existing detection residual checks. This evaluates current/past observable rows
without training or executing another classifier. Its existing checks cover:

* irradiance-reference versus solar measurement;
* SOC step/energy estimate where initialization is actually available;
* availability-adjusted inverter output discrepancy;
* reconstructed controller command discrepancy;
* communication age beyond configured delay;
* configuration integrity;
* received packet versus local solar measurement disagreement.

No new physical residual equation or anomaly threshold is introduced. For a rule
with reported value `v`, existing limit `t > 0`, and unit `u`, each observed tick's
**excess** is `max(v - t, 0)` in unit `u`. Mean excess is averaged over the common
window. Normalized excess is the mean of `max(v - t, 0) / t`. A valid observed
tick with no emitted rule contributes zero *above-limit excess*, not a fabricated
zero raw measurement. Missing/invalid telemetry is excluded from ranking rather
than treated as a normal measurement.

The first SOC-step estimate at an intermediate boundary is unavailable and is
excluded from that metric's sample count. Absolute SOC estimates initialized from
reset are not invented for intermediate checkpoints. All explanations explicitly
describe **mean excess above the existing rule limit**, not raw residual means.

Per-hypothesis output retains units, limits, control/experimental means, normalized
values and the actual experimental ticks where each residual rule fired. Relative
reduction is `(control - experimental) / control` only when normalized control
excess exceeds `1e-9`; otherwise it is `None`, avoiding division by near zero.

## Ranking rules — no weighted score

1. Require completed experiments with identical time windows, finite sufficient
   observations, matched external conditions/RNG audits and comparable controls.
2. Read the existing energy-ledger balance and renewable-balance residuals. A
   reported absolute residual above `1e-8 kWh` excludes that experiment from
   ranking. No new energy accounting is performed.
3. Require at least TWO comparable experiments and at least one measurable
   above-limit control abnormality. One supported experiment plus an unsupported
   alternative cannot establish a winner.
4. Use the SAME residual axes for every experiment: the union of observed control
   and experimental abnormalities, including new contradictory symptoms.
5. Apply Pareto dominance: A is no worse on every normalized residual axis and
   measurably better on at least one. No residuals are added together or assigned
   weights. Normalization uses the existing rule limit for that same metric;
   unrelated physical units are never summed.
6. Return nondominated fronts. Equal profiles remain equivalent; incompatible
   trade-offs remain in one ambiguity group. IDs are sorted only for stable
   presentation, never to choose a winner.
7. Comparisons use absolute tolerance `1e-9` and relative tolerance `1e-6`.
   Approximate dominance can cycle near tolerance boundaries; if it does, all
   remaining hypotheses stay in one ambiguity group rather than looping or
   applying an arbitrary preference.

These new tolerances are comparison arithmetic tolerances, not changes to AI or
anomaly-detection thresholds. Delivered-energy changes and ML scores are **never
ranking weights**. Unsupported, invalid, failed, incomplete and unmatched
experiments have no numeric rank. Their absent measurements remain unavailable,
not zero scores.

## Source support is separate from intervention outcome

The existing `SIGNAL_NODES` mapping connects residual observations to relevant
components. An intervention gains partial evidence support only when a relevant
control abnormality was observed and actually reduced beyond tolerance.
Unchanged relevant abnormalities provide weak support; absent relevant symptoms
are Inconclusive, not proof that the hypothesis is false.

`intervention_ranking` reports observable residual-profile fronts when comparison
is justified. `hypothesis_ranking` is withheld if no intervention reduced a
relevant observed abnormality. It can contain equivalent/trade-off groups; those
groups do not establish a source.

A unique top front receives **Stronger relative evidence support** only with
sustained relevant improvement, no new/worsened residuals, and no unresolved
accepted independent-model candidate-group conflict. Otherwise the overall
result is **Inconclusive**, with reasons. A temporary communication flush cannot
establish sustained containment. Remaining abnormalities are always reported.

Energy delivery is reported independently as the existing experimental-minus-
control ledger difference. Negative differences are explicitly labeled worsened
energy delivery, including when a residual improved. Energy gains without
relevant symptom reduction are labeled energy gain only. Neither changes the
residual ranking or proves intent/source correctness.

Phase 1 and Stage B labels and candidate scores remain separate context. Existing
predictions are not overwritten. Scores are never treated as probabilities of
historical source correctness. Unknown/Undetermined does not block a valid
observable comparison; a conflicting accepted candidate group preserves overall
uncertainty without replacing the measured residual ranking.

Every result retains `historical_source="Not established"`. All experiments are
prospective from the current checkpoint, not historical causal verification.
No attack is inferred simply because a measurement route or controller command
improves behavior.

## Recorded evidence and ground truth

Approved recorded evidence uses the existing residual signal names, finite values
above positive limits, pre-checkpoint ticks, and backend-generated `tN:signal`
IDs. Links are included in explanations. Records do not replace the unchanged
residual thresholds or create arbitrary score bonuses. Unknown free-form fields,
samples, labels, injected targets, schedules and correctness flags are not
returned or used for rankings. At most 256 records are accepted.

Only the snapshot's intended physical configuration is read to initialize the
existing residual extractor. The comparison never reads its schedules, seed,
actual source or evaluation labels. The underlying simulator retains schedules
privately for faithful behavior, as in Step 3.1/3.2.

Tests change hidden attack-record labels and evaluation metadata, forbid
`ground_truth()` accessor calls, and verify identical results/rankings. Separate
tests show sensor malfunction and sensor spoofing yield identical comparisons.
Tests also confirm the live runtime, snapshot, all three existing branches,
ledgers and database records remain unchanged.

## Actual demonstrations

The demonstrations reuse Step 3.2's setups: seed 42, hour 17, transport delay 3,
snapshot at tick 10, and 20 experimental ticks (10–29, ending boundary 30).
Known scenario descriptions below are offline setup context, not ranking inputs.

| Example | Actual result |
| --- | --- |
| Controller manipulation; controller, sensor and link hypotheses | Controller ranks first. Its controller-rule mean excess falls **2.3 → 0 kW**; delivered energy changes **+0.768 kWh**. Sensor/link profiles share a lower trade-off front; no confirmed source is returned. |
| Unrelated solar intervention in that controller scenario | No relevant symptom improvement; energy difference **0 kWh**. |
| Replay plus one-time communication flush | Energy difference **−0.336054 kWh**, added stale-telemetry symptoms, and **Inconclusive** source assessment. |
| Sensor fault versus sensor spoofing hypotheses using the same measurement route | Equivalent tied profiles despite **+1.775492 kWh** each. Overall **Inconclusive**; new transient packet/local disagreement is retained. |
| Shutdown inverter plus unrelated controller/solar interventions | No relevant source improvement; **Inconclusive**. The controller intervention leaves inverter output at zero. |
| Supported controller hypothesis plus unsupported inverter repair | Repair remains untested/unranked. With only one comparable experiment the overall result is **Inconclusive**. |
| Sensor bias, controller versus solar interventions | Incompatible residual trade-off: solar/inverter residuals improve but packet/local disagreement appears. No arbitrary winner. |

Example generated explanation:

> controller_policy_residual: mean excess above its existing rule limit changed from 2.3 to 0 kW. Delivered-energy difference is +0.768 kWh (experimental minus control). This is prospective intervention evidence, not proof of the historical source or malicious intent.

Actual complete results are saved in
`outputs/shadowtwin-comparison/demonstrations.json`; concise explanations/rankings
are in `demonstration_summary.json`. No application logic contains their expected
energy values or known injected source labels.

## Bounds, validation and scope

Batch input requires 2–6 unique caller-supplied hypotheses with a common checkpoint
identifier. Common duration is a positive integer, at most the existing 1,000-tick
advance limit. Total planned work is capped at **480 branch-ticks**, counting both
control and experimental branches, and must fit the captured absolute horizon.
Limits are validated before any experiment runs. For example, three hypotheses
for 40 ticks use 240 branch-ticks. Failed/unsupported alternatives are never
automatically replaced with a more successful intervention.

Focused verification covers comparison logic, Step 3.1 cloning, Step 3.2
experiments, simulator physics, faults, cyberattacks, energy accounting, the recent
scheduling fix and selected runtime/API regressions. Full project regression and
frontend checks are deferred to the integration milestone; no frontend build or
model-training/evaluation workflow is run here. Final results and preservation
hashes are recorded under `outputs/shadowtwin-comparison/verification.json`.

Actual final verification: **198 focused backend tests passed, 0 failed**,
including **27 new comparison tests**, all 34 Step 3.1 tests and 25 Step 3.2
experiment tests, plus existing physics, scheduling, accounting and selected API
regressions. One existing Starlette deprecation warning remains. Full backend,
frontend tests, TypeScript and production build were not run during Step 3.3.
Hash checks verify no frontend changes and eight unchanged model artifacts;
only the existing ShadowTwin package exports changed alongside the new files.

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_shadowtwin_comparison.py backend/tests/test_shadowtwin_experiments.py backend/tests/test_shadowtwin.py -q
```

Changed this step: new `comparison.py`, package exports, new
`test_shadowtwin_comparison.py` and this document. No frontend, simulator,
intervention, scheduling, AI threshold, model artifact, database schema or API
contract was modified by Step 3.3. No commit or push was made. Step 3.4, Phase 4,
autonomous selection, Proof Mode and unrelated improvements are not implemented.
