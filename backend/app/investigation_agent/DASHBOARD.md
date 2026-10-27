# Autonomous investigation dashboard — Phase 4.3

The Investigation page adds an agent panel alongside the existing manual
ShadowTwin tools. The Phase 4.1 planner and Phase 4.2 orchestrator still make
all experiment and evidence-fusion decisions. Optional progress callbacks report
actual execution milestones; they do not change selection or assessment.

## API and authentication

All five routes require the existing authenticated session. POST requests also
validate browser Origin against the API origin or supported local app origins.

* `POST /api/agent/investigate`: capture a current snapshot and start manual
  investigation. Requires `expected_run_id`; `incident_id` is optional.
* `GET /api/agent/status`: confirmed mode, active/latest job and recent summaries.
* `GET /api/agent/investigations`: retained job summaries.
* `GET /api/agent/investigations/{id}`: actual progress and completed report.
* `POST /api/agent/auto-mode`: explicitly enable or disable automatic triggering.

Default budget: three experiments, twenty ticks per experiment branch, maximum
480 total branch ticks. Strict request bounds allow at most three experiments,
1,000 duration ticks and 480 branch ticks, and reject a duration that cannot fit
one paired experiment. The existing orchestrator enforces the actual work limit.

## Trigger and concurrency

Automatic mode defaults OFF, and returns OFF after a backend restart. The runtime
notifies the coordinator after accepted incident records are persisted, without
requiring a browser or polling incident history. Only newly detected, current,
open incidents after enabling qualify. The existing planner must find supported
current observable evidence before a snapshot is captured for execution.

An initially insufficient incident can qualify later if its genuinely new current
observations support an experiment. A started incident cannot automatically run
again in the same simulation run. Busy incidents receive a recorded skip; there
is no pending queue or automatic retry. Disabling prevents new work while allowing
an already running isolated investigation to finish safely.

Snapshot capture and approved evidence projection use the existing runtime lock;
experiments execute outside that lock in a worker thread. Autonomous and manual
ShadowTwin execution share one heavy-work guard. A synchronous reservation protects
manual requests while awaiting snapshot capture. Identical manual requests for
the same run, incident and tick return the existing job instead of re-executing.
Reset changes the run ID, clears deduplication scope, and marks older reports stale;
late results cannot become the latest result for the new run. Shutdown waits for
the detached worker before releasing the shared guard or closing the runtime.

## Evidence and lifecycle

The approved context accepts at most the latest 256 recorded residuals, matching
the existing ShadowTwin bound. Full durable incident history is unchanged.
Hidden simulator schedules and injected labels do not enter planner/fusion
contexts. Only the existing experiment engine receives the opaque detached
snapshot. Experiments do not modify live physics, schedules, ledgers or storage.

Reports show original AI outputs, actual experiment selection reasons, paired
measurements, energy deltas, adaptive decisions and uncertainty. Positive symptom
changes do not establish a fault or cyberattack source. Historical incident ticks
and the current prospective snapshot are labeled separately.

Use one backend worker, as in the existing launch script: coordination is local
to that process. At most twenty reports are retained in memory; restarting loses
agent history but preserves existing incident persistence. Progress events are
bounded, and manual deduplication keys are capped per run. Unsupported diagnostic
interventions, historical replay and live recovery are outside this integration.
