# Phase 3 Step 3.1 — ShadowTwin foundation

This is a backend-only, in-memory simulation foundation. It reuses
`MicrogridSimulator`, `FaultEngine`, `AttackEngine`, `EnergyLedger`, and the
existing runtime lock. It adds no HTTP endpoints, UI, database tables, model
inference, intervention-selection logic, scoring or ranking.

## Capture and fork

```python
from app.shadowtwin import ComparisonFrame

# Use inside backend code with an existing SimulationRuntime. The optional
# at_tick guard rejects capture if the live clock has already moved on.
checkpoint = await runtime.shadow_snapshot("operated", at_tick=100)
left = checkpoint.fork("branch-a")
right = checkpoint.fork("branch-b")

left_rows = left.advance(20)
right_rows = right.advance(20)
frames = [ComparisonFrame.from_rows("experiment-1", {
    left.branch_id: a, right.branch_id: b,
}) for a, b in zip(left_rows, right_rows)]
```

`next_tick=100` means ticks 0–99 have already executed; the next observation is
tick 100. Capture at the desired boundary, normally while paused, or omit
`at_tick` to capture the actual current boundary under the lock. A request for a
different past or future tick is rejected; historical time travel is not inferred
from a seed. Standalone simulators can be captured with
`SimulationSnapshot(simulator, at_tick=simulator.tick)`.

The runtime can capture `operated`, `baseline`, or `faulty_uncorrected`, pairing
each simulator with its own existing ledger. Capture from a **single checkpoint**
when creating matched experimental branches. Baseline/uncorrected/operated states
may already differ due to existing interventions; they are not interchangeable
initial states.

## Mechanism and ownership

A checkpoint deep-copies the complete simulator and ledger object graph together.
This preserves:

* all six current RNG states, including Gaussian caches;
* battery energy, weather/cloud state, current configuration and next tick;
* pending timestamped packets, latest controller inputs and message counters;
* stuck-sensor state, previous inverter request and firmware visibility state;
* active and pending fault/attack schedules, cancellation records and events;
* telemetry history used by replay and stuck-sensor behavior;
* internal aliases, particularly the active fault and `_last_fault` reference.

Each fork copies the checkpoint again. No runtime, worker task, lock, store,
detector, classifier or incident tracker is copied. Branch advancement calls the
existing simulator's `step()` and its own existing ledger's `update()`. It never
calls the runtime's `_advance()` or persistence functions. Checkpoints remain
usable after the live source advances, is corrected, or resets.

For a standalone simulator without a supplied ledger, accounting is reconstructed
by applying the existing `EnergyLedger` to its complete recorded telemetry, not
by rerunning physical simulation. Missing/nonconsecutive history or a supplied
ledger with mismatched configuration, tick count, or battery energy is rejected.

## Matched conditions and determinism

Unmodified forks produce exactly identical existing observable telemetry in the
same Python environment. All random streams start at their captured positions;
cloning does not reseed them. Existing independent weather draws keep irradiance
and demand matched even when branch-local sensor noise consumes different
measurement draws. Physics and random-number consumption in the original engine
are unchanged.

Future interventions that change conditional random draw counts can cause later
measurement, communication, security or attack noise streams to diverge. This
step guarantees cloned initial RNG state and identical continuation with the
same operations, not a new common-random-number mechanism across every possible
intervention. No such intervention framework is implemented here.

## Observable comparison data and ground truth

`ComparisonFrame` contains an opaque caller-supplied experiment ID, the shared
tick, and detached telemetry dictionaries keyed by opaque branch IDs.
`branch_ids` returns the stable sorted identifiers. Both direct construction and
`from_rows()` project approved observable fields and require matching ticks and
elapsed times.

Existing names and units are retained: irradiance, actual/measured solar power,
battery SOC/energy/power, demand/delivery, controller commands, inverter
requested/actual output, losses, communication observations, redundant sensor
values, and security-window observations. Configuration hashes are existing
recorded observations, not inferred attack labels. Projection also covers nested
controller-packet and security records; unknown fields and nested labels are
excluded. Numeric fields reject containers and non-finite values.

The existing islanded simulator does not model grid import/export. Those fields
are explicitly `None` (unavailable), never invented zero values. No new physical
measurements, losses or balances are calculated by this module.

Private checkpoint/branch state necessarily retains schedules to reproduce the
simulation. It is **not investigation evidence** and must not be passed to future
hypothesis-selection code. The comparison frame contains no seed, schedule,
target, true origin, training label, engine record or automatic source choice.
There is no new connection to the investigation or classification pipeline.
Python private attributes are an internal boundary, not a sandbox against code
that deliberately introspects objects.

## Limits

* In-memory current-state capture only; no serialized checkpoint format or
  persisted historical checkpoint registry.
* At most 1,000 ticks per `advance()` and 10,000 absolute ticks per experiment.
  Runtime capture also respects a smaller configured runtime horizon. Exhausting
  the horizon is allowed; advancing beyond it is rejected before any steps run.
* Full history is copied to preserve replay behavior. Capture/fork memory and
  copy time grow with existing history; branch count is caller-managed.
* Capture of a live runtime must use `shadow_snapshot()` for lock protection;
  standalone capture assumes its caller is not concurrently mutating the source.
* Shadow branches are intended for sequential use by one experiment owner;
  concurrent mutation of an individual branch is not supported.
* No cross-Python-version numerical reproducibility guarantee is made.

## Verification

Run the focused tests from the repository root:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_shadowtwin.py -q
```

Tests cover identical initial and intermediate states, six RNG states, active
sensor faults, replay, communication degradation, stealth firmware changes,
multi-stage attacks, inverter delay, future schedules, mutable state isolation,
source reset/correction, copied/reconstructed energy ledgers, matching clocks,
ground-truth filtering, exact-tick guards, limits, lock protection and absence of
live state/database/ledger side effects for all three existing runtime branches.

The focused regression run also covers existing simulator, fault, attack,
sustainability and fault-scheduling modules plus relevant API tests. No model
retraining or extensive ML evaluation is required. Results for this implementation
are recorded under `outputs/shadowtwin-foundation/`.

Actual final result: **146 focused backend tests passed, 0 failed**, including
34 new ShadowTwin tests; one existing Starlette deprecation warning. The full
backend suite, frontend suite, TypeScript checks and production build were not
rerun during this backend-only step. File hashes confirm no frontend or model
artifact changes relative to the start of Step 3.1.

A standalone example captured tick 100 and advanced two forks to tick 120 with
20 identical observations; the source remained byte-for-byte unchanged at tick
100. The maximum energy-balance residual was approximately 3.55e-14 kWh. See
`outputs/shadowtwin-foundation/example.json` for actual comparison frames and
ledger snapshots, and `verification.json` for preservation and test results.

The earlier uncommitted equipment fault-injection fix is preserved. Root `src/`,
unused `frontend/`, styles, dependencies, physics, AI models and existing endpoint
contracts are unchanged by Step 3.1. Steps 3.2, 3.3, 3.4 and Phase 4 have not been
implemented.
