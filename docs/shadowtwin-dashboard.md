# Phase 3 Step 3.4 — Dashboard and live API integration

Completed: the existing Investigation page now includes **ShadowTwin — Virtual
Investigation**, backed by real isolated simulations. No new page, navigation
item, simulation engine, ranking algorithm or AI classifier was introduced.

## Public API

`POST /api/shadowtwin/compare` follows the existing `{ "data": ... }` envelope and
error conventions. Example body:

```json
{
  "duration_ticks": 20,
  "expected_run_id": "current-run-id",
  "incident_id": "optional-existing-incident-id",
  "hypotheses": [
    {
      "hypothesis_id": "solar_fault",
      "component": "solar_sensor",
      "mechanism": "Possible solar sensor malfunction",
      "intervention": "use_redundant_solar"
    },
    {
      "hypothesis_id": "controller_manipulation",
      "component": "controller",
      "mechanism": "Possible controller command manipulation",
      "intervention": "restore_controller_policy"
    }
  ]
}
```

The incident and expected-run references are optional for other API clients; the
dashboard sends its observed run ID and selected incident when available. No
internal snapshot, injected target, schedule, training label or evaluation flag
is accepted. Unknown request fields are rejected.

Pydantic validates 2–6 hypotheses, unique identifiers, known components,
supported component/intervention pairs, nonblank bounded descriptions, integer
duration, and the 480 total control/experimental branch-tick budget. Identical
component/action/mechanism duplicates are rejected; distinct explicitly supplied
explanations may legitimately use the same intervention and return a tie.
The engine independently enforces its captured horizon and 1,000-tick call limit.

Errors use the existing frontend API error mechanism: malformed/unsupported input
and limit violations return 422; a stale expected run or busy analysis returns
409; an unknown incident returns 404. Runtime snapshot failure is reported rather
than producing a success result. No request validation mutates live state.

## Snapshot, threading and isolation

The existing `SimulationRuntime.shadow_snapshot()` capture logic is factored into
a lock-held helper. New `shadow_context()` captures the operated snapshot, current
run identity, tick and permitted incident context under the SAME existing runtime
lock. The snapshot pairs the correct simulator and its existing energy ledger.

After capture, `compare_hypotheses()` runs through `asyncio.to_thread()` outside
the live lock. The event loop and normal simulation controls remain available.
A separate application-level lock admits at most one ShadowTwin comparison per
process and rejects concurrent submissions instead of queuing unbounded work.
Cancellation retains that guard until the bounded worker finishes. Continue
using the project's existing single-worker API launch configuration.

Workers receive only detached snapshots and projected incident evidence, not a
live runtime or database. They do not step live branches, update schedules,
change ledgers, write experimental incidents or overwrite model predictions.
Results retain original `run_id`, `snapshot_tick`, incident identity and comparison
ID. `current_run_id` and `run_changed` explicitly describe a reset that occurs
during work. Later live advancement does not change the captured experiment.

Historical incidents are reference-only: their old evidence/model assessments are
NOT applied to a new current run. Their run IDs are returned separately and the
UI explicitly states that no historical reconstruction was performed. An absent
incident permits a manual current-state experiment with no invented evidence.

The response preserves Step 3.3 rankings, status, explanations, residual summaries,
energy differences and uncertainty. The adapter removes duplicate frames/unused
ledger detail and selects only chartable observable telemetry fields. It never
returns snapshot objects, RNG states, queued messages, schedules or hidden targets.

## Investigation panel

The active frontend remains root `src/`. The unused `frontend/` app is untouched.
The new panel is appended to the existing Investigation workflow, preserving the
source diagnosis, AI Security Assessment, Cytoscape graph, node evidence, timeline,
correction button and incident switcher. Existing page layouts and global CSS
were not rewritten. New CSS is scoped to the ShadowTwin panel.

The panel reuses the existing Card/Button/Badge/EmptyState components and existing
Recharts-based `TimeSeriesChart`. The application shell supplies its already
polled system state through Outlet context; no extra polling loop is added.

Six unchecked manual hypothesis choices cover accidental/manipulated solar
measurement, accidental/manipulated controller behavior, and stale/manipulated
communication. These are proposed explanations, not new simulator fault/attack
types. They map only to:

* `use_redundant_solar` — `solar_sensor`;
* `restore_controller_policy` — `controller`;
* `flush_communication` — `communication` (one-time, temporary).

Users select 2–6 hypotheses and a conservative default of 20 ticks. Client budget
checks supplement authoritative server validation. No checkbox is selected from
an injected target or hidden source. Different explanations using the same action
can remain observationally equivalent even when the action improves delivery.

Results show source-evidence assessment and intervention outcome separately,
actual delivered-energy differences in kWh, backend ranking-front positions,
backend explanations, residual changes and warnings. A visible warning states
that prospective experiments do not independently prove historical attack origin.
Backend Inconclusive, equivalent/trade-off groups, unsupported/failed experiments
and unavailable measurements remain explicit. There are no new confidence scores
or frontend rankings.

One selectable control-versus-ShadowTwin chart displays actual inverter output,
requested output, delivered power, solar measurement or battery SOC. Its tick
labels and kW/% units come from the selected measurement and returned rows.
Energy differences use backend ledger values; the UI does not integrate power,
invent grid-import savings, replace measurements or simulate successful outcomes.
Missing paired measurements render an empty state rather than fabricated values.

Repeated submissions are synchronously locked. Loading/error states leave the
existing investigation intact. Incident/run changes invalidate old responses and
clear old results. A reset reported by the server is explicitly marked with the
captured run identity. Changing form selections also clears their previous result.

## Actual verification

* **Full backend: 359 passed, 0 failed**, four existing non-failing warnings.
* **Full frontend: 90 passed, 0 failed**.
* TypeScript and production build passed, including the final scoped CSS changes.
* No lint script is configured; none was introduced.
* New focused integration coverage: 21 API tests and 15 panel tests. Existing
  Investigation, graph, simulation and all ShadowTwin tests remain passing.

API tests cover real comparisons, projection, input limits, ties, missing
evidence, source-label independence, historical references and actual reset/step
requests during a worker. They verify all three live simulators, energy ledgers
and complete database contents remain unchanged by analysis. Unknown AI states
remain supported by the existing comparison tests. Frontend tests verify exact
requests, backend values, charts, errors, duplicate prevention and stale responses.

Desktop browser verification used the real local API with unchanged validated
models:

1. Injected controller manipulation using the existing dashboard, advanced to
   tick 40, and ran two hypotheses from Investigation. Controller intervention
   ranked first: mean above-limit command residual **2.3 → 0 kW** and delivered
   energy **+0.768 kWh**. The unrelated sensor action had zero energy gain.
2. Injected a sensor bias through the existing fault controls and advanced to tick
   40. The redundant-solar action produced **+1.448665 kWh**, with a genuine
   residual trade-off; the overall result remained **Inconclusive**.
3. Compared solar malfunction and manipulation explanations. Both produced
   **+1.448665 kWh** and the same measured residual profile, and the UI displayed
   an equivalent tie and **Inconclusive**, not a forced winner.
4. Compared live ticks, fault/attack schedules, uncorrected schedules and all
   sustainability values before/after controller and sensor experiments: unchanged.
5. Reset while results were displayed: old results cleared. A subsequent
   historical-incident reference captured the NEW run at tick 0 and displayed the
   historical-reference limitation explicitly, with no old evidence reused.
6. Verified graph node evidence, existing correction success, AI assessment,
   history and sustainability navigation, and actual Start/Pause/Resume events.
   Deterministic stepping used the existing real API. Final state is a fresh
   normal run, paused at tick 0 with no faults or attacks.

Desktop screenshots and real API/DOM evidence are under
`outputs/shadowtwin-dashboard/`, including `controller-result.json`,
`ambiguous-result.json`, before/after state records and `verification.json`.
Mobile viewport emulation was not exposed by the connected browser; responsive
scoped CSS is provided, but mobile browser verification is not claimed.

## Files and preservation

Modified this step:

* `backend/app/api/runtime.py`
* `backend/app/main.py`
* `backend/app/schemas/api.py`
* `backend/app/shadowtwin/experiments.py` — exports the unchanged supported-action
  mapping for request validation; intervention behavior is unchanged.
* `src/components/layout/AppShell.tsx`
* `src/pages/InvestigationPage.tsx`
* `src/services/api.ts`

Created this step:

* `backend/tests/test_shadowtwin_api.py`
* `src/components/ShadowTwinPanel.tsx`
* `src/components/ShadowTwinPanel.css`
* `src/components/ShadowTwinPanel.test.tsx`
* `src/types/shadowtwin.ts`
* `docs/shadowtwin-dashboard.md`

All earlier uncommitted changes are preserved. Hash checks confirm eight deployed
or original model artifact files are unchanged; existing global CSS, packages,
unused frontend, physical simulator, Step 3.1 foundation and Step 3.3 ranking
implementation are unchanged by this integration. No dependencies were installed,
database schema changed, model retraining/evaluation pipeline executed, commit
created or changes pushed.

Remaining limits are intentional: current-state prospective experiments only,
three intervention mechanisms, temporary communication flushing, uncertain
redundant-sensor health, possible random-stream divergence, tied/trade-off results,
no source proof, no modeled grid import/export, and ephemeral comparisons rather
than a persisted experiment-history service. Each response retains its run/tick
identity. Phase 4, automatic diagnostic selection, autonomous investigation,
containment and Proof Mode were not implemented.
