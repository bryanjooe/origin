# Stage 6 dashboard

The frontend uses React 19, Vite 8, TypeScript, Tailwind CSS 4, Recharts,
Cytoscape.js and Lucide icons, with pinned direct dependencies and a committed npm
lockfile. It is a local client of the existing FastAPI service, not a separate
simulation or a static mock dashboard. There are no CDN fonts, remote images,
external inference services or browser-side fault labels passed to ML.

## Running

Install backend dependencies and train the Stage 2/3 models using README commands.
From the repository root, keep this running in terminal one:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

In terminal two, with Node.js 24.15+:

```powershell
cd frontend
npm ci
npm run dev
```

Browse `http://127.0.0.1:5173`. The Vite development/preview proxy forwards relative
`/api` routes to `127.0.0.1:8000`. Both services must remain running. Ports use strict
selection to avoid silently opening the wrong URL. If an existing process is this
project, reuse it; do not start duplicate backend workers. Fresh clones must train
the saved models; missing artifacts are shown explicitly rather than substituted.
Other machines must install Python/Node prerequisites; the checked-in source does
not depend on this computer's bundled Codex runtime paths.

`npm run build` type-checks and emits a production bundle into ignored `frontend/dist`.
`npm run preview` serves that build with the same proxy on port 5173; stop the dev
server before using preview. This is a local demo hosting arrangement. A separate
public deployment would need an API-origin/reverse-proxy configuration and is not
part of Stage 6.

## Pages and behavior

| Page | Connected functionality |
|---|---|
| System overview | Actual PV, physical SOC, demand/delivery, renewable share, recent events, current-run incident count and documented topology |
| Live simulation | Start/resume/pause, reset, speed, deterministic steps, seed, healthy/new-fault scenarios, all fault modes/severities/durations/schedules and simulated correction |
| Fault investigation | Persistent incident selection, representative and latest diagnoses, candidate alternatives, numeric explanations, timeline and interactive graph |
| Sustainability | Baseline/uncorrected/operated energy comparisons, provenance-aware renewable delivery, losses, unmet demand, efficiencies and balance checks |
| Incident history | Search, severity/status/source filters, pagination, run/incident links, timestamp display and CSV/JSON export |
| Model evaluation | Training/calibration/test dataset counts, artifact availability, quick/full evaluation jobs, per-class metrics, Unknown coverage, confusion matrix and severity breakdown |

Fault-scenario truth is displayed only in a labeled disclosure in Live Simulation.
Severity is scenario intensity, not confidence. A classifier score is explicitly
uncalibrated and does not establish root cause. Unknown, empty data, missing models,
unobserved efficiencies and absent reports are shown as such; no numeric performance
placeholders are inserted. Before the first tick, loaded models are distinguished
from models that are unavailable.

The API's model-metrics endpoint now includes aggregate training/calibration counts
from loaded artifact metadata so the evaluation page can display measured dataset
sizes without inferring them from test rows. No training targets or schedules are
added to inference inputs.

## Polling and mutations

The client unwraps the API's `data` envelope and surfaces backend error messages and
field-level validation. Polling is recursive at roughly one-second intervals, so
one live polling cycle completes before another starts. Aborted/unmounted requests
cannot overwrite current state. Telemetry uses run-scoped tick cursors, deduplicates
and orders readings, drops previous-run points after reset, and keeps a maximum of
240 chart points. Archived full telemetry remains available through the API.

State, energy comparisons and scenario metadata are fetched from distinct endpoints;
they can be separated by a tick while running. A run-ID mismatch is retried rather
than mixing histories. Last successful data remains visible during connection loss
with a stale-data notice, capture time and Retry action. Mutating controls are
disabled when offline. A backend runtime error is also shown explicitly.

Per-page actions prevent duplicate overlapping clicks, report pending/error/success
state and refresh data. The backend's synchronization remains authoritative. Reset
or manual stepping while running is disabled, and server-side conflicts still
surface. Reset and scenario replacement archive history. Correction does not promise
immediate diagnosis recovery: more ticks must be observed.

History filters apply to the on-screen list. Export buttons explicitly export all
history (up to the API's 5,000-row default), independently of those filters. The
history confirmation delay is correctly labeled as alert confirmation time rather
than hidden injection-to-detection delay.

## Charts, graph and accessibility

Recharts displays actual solar, measured solar where relevant, demand, delivery,
battery power and SOC with documented units. Physical simulation values are labeled
separately from sensor-reported values. Chart animation is disabled for live updates.
Cumulative renewable share describes energy delivered over the run, not instantaneous
PV utilization or real-world carbon savings.

Cytoscape renders directed dependencies with separate candidate-source, observed-
symptom and potentially-affected states. Suspected edges are dashed and can be
clicked for dependency descriptions and evidence IDs. Node clicks and an accessible
component selector reveal actual attached telemetry and events. Known links are not
represented as proven transmission. Graph inspection is historical over an incident.
Unchanged report polls preserve graph state; updated graphs retain the viewport.
Canvas initialization is deferred for React Strict Mode and cleanup waits for
Cytoscape readiness, avoiding observer work on a destroyed container.

Layouts adapt at desktop/tablet/mobile breakpoints, with a mobile navigation drawer,
scrollable wide tables, labeled controls, focus outlines, disabled-state feedback,
non-color status text and reduced-motion support. Closed mobile navigation is inert.
The development-only `qa/responsive.html` embeds the real application at 390 × 844
CSS pixels for repeatable mobile checks; it is not included in the production build.
Chart and graph text has companion tables/inspectors. A comprehensive assistive-
technology audit is still outside the checks performed in Stage 6.

## Validation and boundaries

`npm test` runs Vitest/Testing Library checks of actual API envelope/error handling,
fault POST payloads, cancellation, cursor merging, run changes, history bounds,
duplicate mutations, conflict display and unavailable backend behavior. Test-only
responses are fixtures; production pages fetch real API data. Browser checks used
the running FastAPI models and persisted incidents, not the test fixtures.

Stage 7 still needs the final full evaluation, expanded end-to-end demo checks and
final project documentation. Stage 6 adds no new ML-accuracy claim and does not
replace the recorded Stage 2/3 benchmarks with the easier quick workflow suite.
