# Phase 3 Step 3.2 — Controlled hypothesis experiments

Implemented as an internal Python service. There are no new HTTP endpoints,
frontend changes, automatic candidate selection, hypothesis rankings, confidence
scores, recovery verdicts, agents or AI-model changes.

## Interface

```python
from app.shadowtwin import Hypothesis, run_experiment

checkpoint = await runtime.shadow_snapshot(at_tick=100)
hypothesis = Hypothesis(
    hypothesis_id="H1",
    component="solar_sensor",
    mechanism="suspected incorrect measurement",  # Caller hypothesis, not truth.
    intervention="use_redundant_solar",
    duration_ticks=20,
    checkpoint_id="checkpoint-at-100",             # Caller identifier/reference.
)
result = run_experiment(checkpoint, hypothesis, experiment_id="E1")
```

The actual `SimulationSnapshot` is the checkpoint reference. IDs and mechanism
descriptions are caller-supplied labels, not automatically obtained simulator
answers or authenticated checkpoint provenance. Each call creates fresh control
and experimental branches from the same checkpoint. Reusing a checkpoint for
another hypothesis does not reuse mutated branches.

The control advances without additional input choices. The experimental branch
receives exactly the requested supported intervention, at its starting tick.
Both use the existing simulator and energy ledger. No intervention cancels any
fault or attack schedule, resets the whole simulator, edits produced telemetry,
or reads source labels to choose an action.

## Supported interventions

| Intervention | Component | Actual behavior | Duration |
| --- | --- | --- | --- |
| `use_redundant_solar` | `solar_sensor` | Select the existing simulated redundant solar reading for the controller packet before transport and physical calculations | Every experimental tick |
| `restore_controller_policy` | `controller` | Select the already-computed nominal controller command before inverter request, battery and power-flow calculations | Every experimental tick |
| `flush_communication` | `communication` | Clear the pending packet queue and latest received packet, reusing the transport reset previously embedded in `correct()` | One time only |
| `none` | Caller hypothesis component | No additional intervention; useful as a paired control check | None |

Two small opt-in input-choice hooks were added to `MicrogridSimulator.step()`;
they select existing measurements/calculations, not new physics or sensors.
Defaults are false for all existing callers. The communication reset is factored
from the existing correction operation; full correction still cancels faults and
attacks, clears stuck-sensor state, and records its existing event as before.

Selecting the redundant solar sensor is an experimental alternative input, **not
a claim of an authenticated or guaranteed healthy sensor**. Other measurements,
packet manipulation, firmware behavior, applied configuration and inverter faults
remain effective. Selecting the nominal controller cannot cure corrupted received
inputs or damaged actuators. These controls last only for the requested advance;
they do not permanently alter the simulator or rewrite schedules.

Communication flushing is explicitly temporary. Queues can refill immediately,
ongoing replay/manipulation remains scheduled, and waiting for new packets can
reduce energy delivery. A completed flush experiment is not successful attack
containment or a recovery verdict.

Unsupported examples include inverter repair, firmware restoration, deleting an
attack, resetting the whole system, substituting nonexistent trusted sensors,
redundant battery routing, component/intervention mismatches, and arbitrary
optional parameters. The initial controls accept no optional parameters. Such
requests return `unsupported` with no execution tick or fabricated outcomes.

## Result and interpretation

`ExperimentResult` contains caller identity/hypothesis metadata, execution status,
starting and exclusive ending ticks, actual intervention execution tick,
intervention status and duration semantics, control/experimental observations,
existing `ComparisonFrame` pairs, experimental-minus-control observable
differences, existing energy-ledger measurements/differences, warnings and limits.

Numeric differences are direct subtraction at matching ticks; changed boolean or
string observations retain both recorded values. Missing values stay `None`.
Energy values come from the original `EnergyLedger`, including its existing
residuals. Ledger snapshots are cumulative to the common ending tick, including
identical pre-checkpoint history. No new energy-loss formula is introduced.
Grid import/export remain unavailable; there are no invented zero flows.

`completed` means the requested bounded simulation ran; it does not mean a fault
was resolved or a source was proven. Unsupported requests run no branches;
advancement failures return `failed` without invented partial observations or
leaking internal error messages. Invalid durations/horizon requests raise
`ValueError` before advancement.

All supported experiments are `prospective_intervention`. The current-state
checkpoint limitation is unchanged. `mode="pre_incident"` and other historical
requests return `unsupported_checkpoint_provenance`; no historical state or
incident provenance is inferred. A missing checkpoint is explicitly unsupported.
The service does not build a checkpoint registry or retrospective replay engine.

## Randomness and ground-truth boundary

Branches start with the six RNG states preserved by Step 3.1. Results audit actual
irradiance, solar availability, demand and timing equality, and starting/ending RNG
state equality. Divergence produces explicit limited-comparison warnings. This
does not rewrite conditional RNG consumption or prove that every difference is
causal. All supported demonstration cases retained matched external conditions
and RNG states.

Private snapshots keep schedules for faithful simulation, but intervention
selection uses only the caller's requested intervention/component pair. The
experiment service never queries `ground_truth()`, schedule records, injected
targets or actual-source identifiers. Comparison data reuses the foundation's
nested observable-field projection. RNG audits return equality flags, not raw
random state or hidden labels. No result is sent to the live investigation or AI
pipeline.

Tests modify evaluation-only attack records while preserving active behavior and
make ground-truth accessor calls fail. Experiment outputs remain identical.
Other tests verify unrelated disturbances remain active, no schedule cancellation
occurs, and the runtime's operated/baseline/uncorrected simulators, ledgers,
telemetry, incident history and database records remain unchanged.

## Actual demonstrations

Seven small deterministic examples used seed 42, start hour 17, communication
delay 3 ticks, a checkpoint at tick 10, and 20 experimental ticks (observations
10–29, ending boundary 30). Scenario setup belongs to the offline demonstration;
it is never an input for automatic hypothesis selection.

| Known offline setup / caller experiment | Actual observation | Delivered energy difference, experimental minus control |
| --- | --- | ---: |
| Solar sensor bias / redundant solar route | Tick-10 reading changes from 11.631956 to 2.046642 kW; downstream effect waits for queued packets | +1.775492 kWh |
| Solar spoofing / same redundant route | Same observed response as the bias example | +1.775492 kWh |
| Controller manipulation / nominal controller | Tick-10 command 2.6 → 5.0 kW; inverter output 4.481433 → 6.785433 kW | +0.768000 kWh |
| Replay / one-time communication flush | Tick-10 inverter output 6.747857 → 0 kW while awaiting packets; ongoing schedule retained | **−0.336054 kWh** |
| Controller manipulation / alternative solar hypothesis | Controller command remains 2.6 kW | 0 kWh |
| Shutdown inverter / wrong controller hypothesis | Inverter remains 0 kW; observations identical | 0 kWh |
| Shutdown inverter / `repair_inverter` | Unsupported; no observations manufactured | Unavailable |

The matching bias and spoofing responses demonstrate an important limitation:
these intervention outcomes alone cannot distinguish accidental from malicious
intent. An improvement is not source confirmation. The worse flush outcome is
retained rather than presented as successful recovery.

Actual rows, matching frames, differences and ledgers are saved in
`outputs/shadowtwin-experiments/demonstrations.json`; concise measurements are in
`demonstration_summary.json`.

## Limits and verification

Experiments require 1–1,000 ticks and must end within the checkpoint's existing
absolute horizon (at most 10,000). No unbounded loops, new runtime manager,
database writes, dependencies, model training or ML evaluation workflow is added.
Memory still grows with the existing checkpoint history and returned rows.

Actual targeted result: **171 backend tests passed, 0 failed**, including **25 new
experiment tests**, the 34 Step 3.1 tests, and existing simulator, fault,
cyberattack, sustainability, scheduling and selected API/runtime regressions.
One existing Starlette deprecation warning remains. The full backend suite,
frontend tests and frontend build were not run during this backend-only step.

An additional default-behavior audit compared the pre-intervention simulator with
the current default execution in eight fixtures: normal, sensor noise, controller
fault, sensor spoofing, replay, controller compromise, firmware tampering and
multi-stage attack. All 320 paired observation ticks and correction-event lists
were identical. Results are retained in `default_behavior_parity.json`.

Run the focused experiment and cloning tests:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_shadowtwin_experiments.py backend/tests/test_shadowtwin.py -q
```

Changed this step: simulator input-choice hooks and communication-reset helper;
ShadowBranch argument forwarding; package exports; new `experiments.py`,
`test_shadowtwin_experiments.py`, and this document. Earlier uncommitted fault-fix
and Step 3.1 work are preserved. Frontend, models, thresholds, physical equations,
database schema and existing FastAPI contracts are unchanged. No commit or push
was made. Step 3.3 ranking/scoring, Step 3.4 frontend, Phase 4, agents, evidence
fusion and Proof Mode are not implemented.
