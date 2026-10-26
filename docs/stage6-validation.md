# Stage 6 validation — 2026-10-26

The frontend was built/tested with Node 24.21.0 and npm 11.19.0; its live Vite
preview ran with the bundled Node 24.22.1. Backend verification used Python 3.12.14.
The committed lockfile and package manifest define the exact installed versions.

## Automated checks

```text
frontend: npm run build     — TypeScript check + production build succeeded
frontend: npm test          — 13 tests passed across 2 files
frontend: npm audit --json  — 0 known vulnerabilities reported
backend: python -m pytest  — 145 passed, 1 dependency deprecation warning
```

Frontend tests verify API response envelopes, JSON fault POSTs, field-level errors,
conflicts, malformed/proxy responses, export identifiers, cancellation, tick ordering/
deduplication, chart history limits, reset/run changes, duplicate mutation protection
and explicit offline behavior. Production code does not use these test fixtures.

The backend change exposes measured artifact training/calibration counts for the
evaluation screen. Its regression test checks those counts from actual fitted
models. All prior physical, ML, graph, persistence, concurrency and API tests pass.

The build separates page, chart and graph chunks. It ships no model artifacts or
SQLite files. Tailwind/PostCSS were updated during implementation after the first
dependency audit; the final audit reported no known issues. This is an audit result
at verification time, not a permanent security guarantee.

## Live browser workflow

The Codex in-app browser loaded the actual dashboard through Vite's API proxy.
All six pages rendered with real saved-model, SQLite and telemetry data:

1. Loaded the zero-tick paused run and advanced a healthy baseline by 20 ticks.
2. Injected inverter derating at tick 20 with severity 0.8 and duration 60.
3. Advanced to tick 40 and observed warning telemetry and a confirmed incident.
4. Opened Fault Investigation; it displayed Actuator/Inverter with an uncalibrated
   classifier score around 98.3%, numeric inverter/request evidence and alternatives.
5. Selected the inverter node and inspected actual attached measurements: request
   5.694 kW, output 1.139 kW at tick 39, with 4.556 kW residual and 0.580 kW limit.
6. Applied simulated correction through the investigation page at tick 40, then
   advanced to tick 60 and observed no active anomaly. The incident resolved at 44.
7. Reviewed sustainability totals: equal-horizon solar generation 8.137 kWh and an
   estimated correction delivery gain of 1.519995 kWh versus the uncorrected run.
8. Opened persisted history and filtered predicted source to Sensor, showing only
   the matching archived record. CSV/JSON export links target the live API routes.
9. Opened Model Evaluation and verified actual training/calibration counts, current
   report profile/provenance, per-class metrics, confusion matrix and severity table;
   launched a real quick held-out evaluation from the UI.

The browser did not consult injected truth to select the diagnosis. Model outputs,
scenario truth and physical telemetry remain visibly distinguished. The measured
proxy/API snapshot is in [stage6-example.json](stage6-example.json). These workflow
checks do not create a new ML-accuracy benchmark or replace the harder full suites.

## Responsive and visual checks

The actual desktop/tablet preview was inspected around 864 CSS pixels wide. A
development-only iframe harness provided a 390 × 844 CSS-pixel viewport for actual
mobile rendering. The overview, drawer opening/navigation and stacked simulation
controls rendered within that narrow viewport. Closed mobile navigation is inert.
Graphs have a component selector alongside pointer interaction; wide metric/history
tables scroll rather than extending the entire page width. Reduced motion is
supported in CSS. A complete cross-browser/assistive-technology audit was not run.

Screenshots were saved locally as `outputs/stage6-dashboard.png`,
`outputs/stage6-investigation.png` and `outputs/stage6-mobile.png`.

A browser-reported MutationObserver exception occurred when navigating away from
the iframe QA harness. It was reproduced with a static iframe containing no React,
GreenGrid or graph code, while application-level error instrumentation did not
capture it. This isolates that exception from the application code under test;
ordinary dashboard navigation and graph interactions worked. Temporary diagnostics
were removed. Canvas setup/cleanup also avoids immediate Strict Mode initialization
on a container that is being unmounted.

## Handoff

The local backend and Vite dashboard are available on ports 8000 and 5173; the
browser-verified run is paused at tick 60 with its resolved incident retained.
Use the README's two-terminal commands on a later session or another computer.

**One stage remains:** Stage 7, final full evaluation, expanded end-to-end demo
validation and final documentation. Stage 6 verifies frontend integration; it does
not claim that final acceptance, field validation or a production deployment is done.
