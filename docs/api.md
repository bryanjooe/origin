# Stage 5 REST API

Launch one Uvicorn worker with the README command. Interactive OpenAPI docs are at
`http://127.0.0.1:8000/docs`; machine schema is `/openapi.json`. Bind to localhost
for this local demo. The API uses polling; WebSockets are not needed for the MVP.
CORS permits the local Vite origins `http://localhost:5173` and
`http://127.0.0.1:5173` for the next frontend stage.

## Response and validation conventions

Normal JSON responses use `{"data": ...}`. Errors use
`{"error":{"code":"...","message":"...","details":[]}}`. Request bodies are
Pydantic-validated with unknown keys and non-finite numbers rejected. Common codes:
422 for invalid inputs/operations, 409 for incompatible runtime state, 404 for
missing records and 503 when no trained model can perform requested evaluation.
No physical simulation fields are silently substituted for absent model predictions.

Power is kW, energy kWh and simulated time seconds. The returned `next_tick` is the
next interval to simulate; latest telemetry refers to `next_tick - 1`. UTC
`created_at` fields describe actual persistence times, separately from simulated
tick/time. They do not claim a real physical event occurred.

## Routes

| Method and route | Behavior |
|---|---|
| GET `/api/health` | Backend/model availability, explicit model-loading errors, polling interval |
| GET `/api/system/state` | Current run/config, running flag, speed, last telemetry/inference and runtime error |
| GET `/api/system/topology` | Known directed component dependencies |
| POST `/api/simulation/start` | Idempotently start; optional `{"speed":2}` in ticks per wall-clock second |
| POST `/api/simulation/pause` | Wait for an in-progress tick, then pause; idempotent |
| POST `/api/simulation/resume` | Reuse the same worker and current run; same body as Start |
| POST `/api/simulation/speed` | `{"speed":5}`, range 0.1–30 target ticks/second |
| POST `/api/simulation/step` | `{"ticks":20}`, 1–300 ticks, paused only |
| POST `/api/simulation/reset` | Paused only; optional `{"seed":42}`, preserve intended config, archive old run |
| POST `/api/simulation/scenario` | Paused only; new seed/config and optional fault, replacing the live scenario |
| GET `/api/simulation/scenario` | Current scenario metadata, with explicitly labeled separate ground truth |
| GET `/api/scenarios` | Persisted scenarios, newest first; `limit` 1–1000 |
| POST `/api/simulation/inject-fault` | Schedule a validated in-memory fault, or start at the next tick |
| POST `/api/simulation/correct` | Restore simulated components, cancel operated-run faults, retain counterfactual |
| GET `/api/telemetry` | Current or selected `run_id`; cursor `after_tick=-1`, `limit` 1–2000 |
| GET `/api/events` | Cursor `after_id=0`, optional `run_id`, `limit` 1–2000 |
| GET `/api/incidents` | Summary list and total; filter `run_id`, `severity`, `status`, `source`, `search`; `limit`/`offset` |
| GET `/api/incidents/{id}` | Complete persisted evidence, explanation, timestamps and graph |
| GET `/api/incidents/{id}/graph` | Node telemetry/events and evidence-linked suspected paths |
| GET `/api/metrics/sustainability` | Three equal-horizon energy ledgers, comparison estimates and assumptions |
| GET `/api/model/metrics` | Availability, artifact hashes, report provenance and evaluation-job state |
| POST `/api/model/evaluate` | Start an actual held-out evaluation job; optional `{"profile":"quick"}` or `"full"` |
| GET `/api/reports/export` | Download JSON/CSV: `dataset=incidents|telemetry|scenario`, `format=json|csv` |

All physical simulation controls affect only the software simulation. No real
network attack, firmware deployment or device correction is implemented.

## Example scenario

POST `/api/simulation/scenario` while paused:

```json
{
  "seed": 42,
  "config": {"start_hour": 10, "tick_seconds": 60},
  "fault": {
    "kind": "inverter", "mode": "derate", "severity": 0.8,
    "start_tick": 30, "duration_ticks": 120
  }
}
```

Omitted configuration fields use validated `GridConfig` defaults. Fault injection
uses the same fault object, omitting `start_tick` to start at the next tick. Modes
are listed in [simulation documentation](simulation.md). Severity is in (0, 1],
duration 1–10000 integer ticks; time cannot be in the past. All faults must end
within the server's 10000-tick run limit. Overlap is rejected across both operated
and uncorrected comparison schedules. A correction does not cancel the hypothetical
uncorrected schedule, so injecting a new fault before that planned expiry requires
a new scenario. This avoids overlapping faults in comparisons.

## Synchronization and failure handling

A per-runtime asyncio lock serializes all live mutations and consistent reads.
There is one long-lived runner task, reused by repeated Start/Resume calls.
Start never creates a second active loop. Tick simulation/inference runs in a
thread while the lock remains held. Pause waits for that tick; after its response,
no further tick can occur until resumed. Starting repeatedly does not accelerate
the worker unless a different speed is explicitly supplied.

Reset/scenario replacement and manual stepping require a paused worker, returning
409 otherwise. Invalid scenario requests are checked before the existing run is
archived. A fresh run resets RNGs, physical state, feature history and incident
tracking. Configuration/seed are repeatable; UUID run IDs are intentionally unique.
Correction preserves time, battery energy and feature history.

At 10000 ticks the runner pauses automatically. Speed is a target; inference and
database work can reduce achieved throughput. State reads may wait behind a manual
multi-tick Step. Runtime failures pause the worker or mark it failed and require
reset rather than silently retrying a partially advanced physical interval.
SQLite commits are atomic; in-memory physical state is not rolled back on an
unexpected inference/storage failure. Inspect `runtime_error` before continuing.

Use **one process/one worker per database**. The lock is process-local, not a
distributed scheduler. Running independent server processes against the same live
database is unsupported. This is a local demo service rather than a multi-user
deployment architecture.

## Durable history and model evaluation

SQLite tables store scenarios, telemetry plus aligned model outputs, incident
reports, events and evaluation results. Tick telemetry, changed incident snapshots,
events and current scenario/energy metadata commit together. Completed unchanged
incident reports are not rebuilt every tick. IDs are `{run_uuid}:{local_incident_id}`.
Parameterized queries handle user filters. Reset never deletes historical records.

Orderly backend shutdown and reset mark open incidents interrupted without claiming
recovery. On restart, SQLite history is retained; abandoned live scenarios/open
incidents are marked interrupted. A new paused live scenario starts. The application
does not resume an in-memory physical state from a checkpoint. Model artifact SHA-256
hashes are recorded in scenario metadata and evaluation persistence.

Startup loads trusted artifacts from configured paths; it does not train models.
Missing/incompatible models are explicit. Initially displayed saved reports are
labeled as reports from the artifact directory, not a fresh server computation;
threshold/policy mismatches are reported instead of attaching the report. That
check is not proof a sidecar file belongs to a particular training run. Fresh jobs
are linked to current artifact hashes and persisted; they can be restored after
restart only when both hashes match.

Evaluate returns 202 with a job ID. Poll `/api/model/metrics`; status becomes
`complete` or `failed` with an actual error. Duplicate concurrent jobs return 409.
Evaluation uses frozen read-only models in another thread, without changing live
telemetry. Full profile reproduces the Stage 2/3 held-out suites. Quick profile uses
one 360-tick normal anomaly run plus five 120-tick active-fault intervals (one
clear mode per family), and 50 source-classification runs/6999 selected ticks with
the default generator. It is explicitly narrower than the full benchmark. All
existing training-run/seed leakage guards still apply. Missing models are skipped;
no models at all yields 503, not fabricated metrics.

Exports have an explicit row limit (default 5000, max 10000). JSON reports a
`truncated` flag and CSV uses `X-Export-Truncated`; use history pagination for larger
datasets. Incident exports include complete reports; CSV encodes nested structures
as JSON cells. Scenario exports contain clearly labeled simulated ground truth;
inference does not consume that export. Current telemetry/counterfactuals and long
incident evidence remain in memory for the bounded run; SQLite history grows over
time. Retention policies and multi-user access control are outside this MVP stage.
