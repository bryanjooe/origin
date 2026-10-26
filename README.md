# Origin

Origin is a local renewable microgrid simulator and fault-localization dashboard. The
React interface uses the FastAPI service in `backend/`; all values, model predictions,
evidence and evaluation scores come from that API. The dashboard never controls
physical equipment and shows explicit unknown/error states when a model or service is
unavailable.

## Run the integrated project

Use Python 3.11–3.13 and Node.js 22.12+.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm install
# TraceX GreenGrid

Software-only renewable microgrid fault-localization project. **Stages 1–6 are
implemented:** physical simulation, deterministic fault injection, timestamped
communication, controller logs, dependency topology, and a normal-baseline
Isolation Forest anomaly detector with separately labeled residual checks, and a
Random Forest source classifier with confidence-based abstention. Incident reports
now group alerts, trace evidence-compatible dependency paths and explain observations.
FastAPI now serves synchronized simulation controls, real inference, persisted
SQLite incidents and paired sustainability comparisons. A responsive React dashboard
now connects the complete simulation and investigation workflow.

## Setup

Python 3.11 or 3.12, no hardware, external APIs, or paid services. Installation needs
PyPI access; simulation and tests run offline after installation.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m app.simulator --fault normal --output outputs/normal
.\.venv\Scripts\python.exe -m app.simulator --fault inverter --mode derate --severity 0.8 --start 30 --duration 120 --correct-at 110 --output outputs/inverter
```

Start the API and dashboard in separate terminals from this directory:

```sh
PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

```sh
npm run dev -- --port 5173
```

Open `http://127.0.0.1:5173/`. Vite forwards `/api` to the local API. The API starts
paused. Use the Live Simulation page to start a seeded run, pause/resume it, schedule
an injected fault, inspect incidents and apply a simulation-only correction. The API
uses REST polling; the dashboard polls telemetry with a tick cursor and keeps a
bounded chart history. API docs are available at `http://127.0.0.1:8000/docs`.

Copy `.env.example` to `.env.local` only when the API is hosted somewhere other than
the Vite proxy:

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | empty | API origin for a separately hosted backend; empty uses the local Vite proxy. |
| `ORIGIN_DATABASE` | `outputs/server/greengrid.sqlite3` | Backend incident/event database path. |
| `ORIGIN_ANOMALY_MODEL` | `outputs/stage2/anomaly.joblib` | Optional trained anomaly detector. |
| `ORIGIN_SOURCE_MODEL` | `outputs/stage3/source_classifier.joblib` | Optional trained source classifier. |
| `ORIGIN_SECURITY_MODEL` | `outputs/stage5/held_out_fault_attack_origin.joblib` | Optional Stage B fault/attack and origin-layer classifier. |
| `ORIGIN_SECURITY_RESULTS` | `outputs/stage5` | Stage B synthetic held-out reports and metadata directory. |

The backend reads `ORIGIN_*` settings from the process environment. Existing
`TRACEX_*` names remain accepted for compatibility with earlier scripts.

## Train the optional ML models

The simulation and operational controls work without trained models. The dashboard
will show model predictions and held-out evaluation as unavailable until the model
artifacts exist. To enable those features, train both models from the repository root:

```sh
PYTHONPATH=backend .venv/bin/python -m app.detection
PYTHONPATH=backend .venv/bin/python -m app.localization
## Stage 2: train and run anomaly detection

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m app.detection
.\.venv\Scripts\python.exe -m app.simulator --fault sensor --mode bias --start 30 --duration 60 --anomaly-model outputs/stage2/anomaly.joblib --output outputs/scored-sensor
```

Training creates `outputs/stage2/anomaly.joblib`, normal-only training features,
training/calibration manifests, and held-out `evaluation.json`. Artifacts are
generated locally and ignored by Git; rerun training after cloning. Only load
Joblib artifacts you trust. Missing models report an error and produce no predictions.
The scored simulator additionally exports per-tick `anomaly_scores.json` and
`anomaly_events.json` (alert ticks, not deduplicated incidents), including detection
time, ML score/status, residual checks and affected signals. Core telemetry remains
separate from alerts and hidden scenario metadata.

Default evaluation uses 24 normal training runs, 8 normal calibration runs, 8 held-out
normal runs, and 96 held-out fault runs covering all 16 modes at three severities.
ML active-fault-tick recall is **29.68%**, combined ML/rule recall **71.89%**, and
both have **0.84%** false positives on held-out normal ticks. These are synthetic
results; some faults are missed. Scores are not probabilities or source confidence.
See [detector methodology](docs/detection.md) and the
[measured validation report](docs/stage2-validation.md).

## Stage 3: train and run source localization

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m app.localization
.\.venv\Scripts\python.exe -m app.simulator --fault inverter --mode derate --severity 0.8 --start 30 --duration 120 --correct-at 110 --anomaly-model outputs/stage2/anomaly.joblib --source-model outputs/stage3/source_classifier.joblib --output outputs/localized-inverter
```

Training generates a persisted `source_classifier.joblib`, feature CSV, training
manifest, validation results and held-out test report in `outputs/stage3`. This
directory is ignored by Git; run the command after cloning. Source scoring can
also run without `--anomaly-model`. It adds `source_predictions.json` with ranked
candidates, uncalibrated classifier confidence, actual residual observations,
input features, and explicit Unknown results for low confidence, ambiguity or
missing initialization. Telemetry and scenario truth remain separate files.

Six learned classes are Normal, Sensor, Communication, Controller,
Firmware/Configuration, and Actuator/Inverter. Unknown is an abstention, not a
seventh trained source. Hypotheses are not proven root causes. Default confidence
and top-two margin limits are 0.65 and 0.15, fixed before validation/test scoring.

On 104 held-out runs, overall accuracy is **81.57% including Unknown as incorrect**,
coverage **89.08%**, and accuracy among accepted predictions **91.56%**. Unknown
rate is **10.92%**; normal recall is **70.35%**, mainly due to abstentions. These are
synthetic per-tick classification results, not end-to-end incident performance.
See [localization methodology](docs/localization.md) and
[Stage 3 validation](docs/stage3-validation.md).

## Stage 4: investigate an incident

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m app.simulator --fault inverter --mode derate --severity 0.8 --start 30 --duration 120 --correct-at 110 --anomaly-model outputs/stage2/anomaly.joblib --source-model outputs/stage3/source_classifier.joblib --investigate --output outputs/investigated-inverter
```

`--investigate` adds `incidents.json` with confirmation/recovery times, ML and
residual evidence, a symptom timeline, ranked source hypotheses, diagnostic checks,
and a graph containing component telemetry and events. The anomaly model is
required; without a source model incidents explicitly report Unknown. Fault labels,
schedules and hidden physical values are not supplied to the investigation layer.

Three consecutive warning ticks confirm an incident; critical alerts confirm
immediately. Five consecutive quiet ticks resolve it. The representative diagnosis
comes from the alert with the largest anomaly score, while the latest alert-time
diagnosis and changes are retained separately. Resolution means alerts cleared,
not that a correction is proven to have caused recovery.

Suspected edges cite actual symptom evidence and documented dependencies. They do
not prove transmission or causation. Unknown-source incidents retain observed
symptoms without inventing a propagation origin. Stage 4 adds no new model training
or accuracy claim. See [investigation methodology](docs/investigation.md),
[validation](docs/stage4-validation.md), and
[measured compact examples](docs/stage4-examples.json).

## Stage B: classify fault versus attack and localize origin layer

Stage B adds an offline nature classifier (Normal / Accidental fault / Cyber attack /
Undetermined) and an independent origin-layer classifier (Sensor, Communication,
Controller, Firmware-Config, Actuator-Inverter / Unknown). It does not change the
existing anomaly detector or source classifier. The API and dashboard expose Stage B
held-out reports on Model Evaluation and telemetry-derived attribution on Fault
Investigation. Both new models use
causal 20-tick telemetry windows that begin at the existing anomaly detector's first
fire inside the simulated event. Runs with no in-event detector fire remain misses;
they do not receive a fabricated attribution. Stage 5 compares Random Forest and
Gradient Boosting using validation-only macro-F1, selects per split, and sigmoid
calibrates probabilities on run-disjoint validation windows. Low-confidence results
abstain; calibration quality is reported on held-out runs.

```sh
PYTHONPATH=backend .venv/bin/python -m app.security_analysis \
  --repeats 9 --ticks 240 --seed 72100 --output-dir outputs/stage5
```

The generator covers normal runs, all fault modes, all eight attack types, severity,
start-time and duration variation, and naive/moderate/stealthy attacks. It partitions
whole runs and seeds before model fitting, and also evaluates a separate test split
with every stealthy attack held out of training. The command writes
`outputs/stage5/incident_features.csv`, `metadata.json`, the two evaluation JSON
reports, `telemetry_audit.json`, and `fault_attack_origin.joblib`. Feature columns are explicitly allowlisted;
scenario labels and run manifests are stored separately from inference features.
The security feature extractor rejects telemetry containing attack/fault engine
records. Attribution evidence is counted from actual telemetry and is described as
indicators, not proof of intent or a proven root cause. See
[Stage B methodology and results](docs/stage-b-validation.md).

The dashboard's Model Evaluation page shows Stage B held-out nature,
fault-vs-attack, and origin-layer scores; per-attack and stealth breakdowns;
stealth-held-out generalization; signal importances; and the comparison with the
preserved source classifier. Fault Investigation shows a separate security
assessment with confidence, alternative origin layers, and counted telemetry
observations. The additive `/api/security/metrics` route serves saved synthetic
reports. Incident detail computes a causal security window from persisted observable
telemetry; no fault schedule or attack-engine record enters the prediction.

## Stage 5: run the local API

Install the updated requirements, train both models using the Stage 2/3 commands,
then start **one server process with one worker** from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

Open [interactive API documentation](http://127.0.0.1:8000/docs). The server starts
paused; use Start/Resume for live ticks or Step for deterministic advancement while
paused. Poll state/telemetry at roughly one-second intervals. Repeated Start calls
reuse the same worker. Missing models explicitly report unavailable, while physical
simulation remains usable. No predictions or incidents are fabricated.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/simulation/start -ContentType application/json -Body '{"speed":2}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/simulation/pause
```

For a complete measured HTTP demo after training, run in a second terminal:

```powershell
.\.venv\Scripts\python.exe scripts/verify_api.py
```

This archives the current run, creates a seeded inverter-fault scenario, advances
it, applies simulated correction, checks persisted reports/energy balance and
executes the real quick held-out evaluation. Results are saved to
`outputs/stage5-live-check.json`; the final live run is left paused.

SQLite defaults to `outputs/server/greengrid.sqlite3`. Reset preserves archived runs
and incidents; restart retains history and starts a new paused run. Open incidents
are marked interrupted when the run/backend ends without observed recovery.
Model paths/database location are configurable through environment variables in
[.env.example](.env.example); the file is a reference and is not loaded automatically.
See [API contract](docs/api.md), [energy accounting](docs/sustainability.md), and
[Stage 5 validation](docs/stage5-validation.md).

## Stage 6: run the complete dashboard

Use Node.js 24.15+ (build/tests used 24.21.0; local preview used 24.22.1). Keep the backend command above running
in one terminal, then open a second terminal at the repository root:

```powershell
cd frontend
npm ci
npm run dev
```

Open **[TraceX GreenGrid](http://127.0.0.1:5173)**. Vite forwards `/api` requests
to FastAPI on port 8000; no external APIs or paid services are required. If these
ports are already serving this project, reuse them instead of starting duplicates.
Stop foreground development servers with Ctrl+C in their respective terminals.

The six pages cover System Overview, Live Simulation, Fault Investigation,
Sustainability Analysis, Incident History/Reports and Model Evaluation. Controls
start/pause/reset/step the real simulator, schedule all implemented fault modes,
apply software-only corrections, inspect evidence-linked Cytoscape nodes/edges,
filter/export persisted incidents and run held-out model evaluation. Ground truth
is in a separate disclosure panel. Missing models and lost connections are explicit.

Frontend checks:

```powershell
cd frontend
npm test
npm run build
```

After building, `npm run preview` serves the production bundle on port 5173 with
the same API proxy; stop the dev server first. The backend must still be running.
The frontend lockfile pins the resolved dependency tree. Do not commit `dist`,
`node_modules`, generated models or SQLite files.

See [frontend architecture and usage](docs/frontend.md) and
[Stage 6 validation](docs/stage6-validation.md). **One stage remains:** Stage 7,
the final full evaluation, end-to-end demo validation and final documentation.

## Structure

```text
backend/
  app/
    simulator/          # Validated immutable config, physical model, CLI
    fault_injection/    # Fault families, validated schedules, scenario truth
    propagation/        # NetworkX dependency graph and downstream traversal
    detection/          # Causal features, normal-only ML, calibration, evaluation
    localization/       # Supervised source classifier, confidence/Unknown, evaluation
    explainability/     # Incident lifecycle, observed evidence, deterministic explanations
    api/                # One synchronized simulation worker, model loading/evaluation
    schemas/            # Pydantic HTTP contracts
    database/           # Transactional SQLite history
    sustainability/     # Conserved energy/provenance ledgers and paired comparisons
    main.py             # FastAPI app and endpoints
  tests/                # Deterministic physics, faults, graph, export checks
  requirements.txt
frontend/
  src/
    pages/              # All six dashboard pages
    components/         # Charts, graph inspection and shared UI
    hooks/              # Bounded live polling and mutation handling
    services/           # FastAPI envelope/error client
    types/              # TypeScript response contracts
  qa/                   # Development-only mobile viewport harness
  package-lock.json
docs/simulation.md      # Equations, units, and limitations
pyproject.toml          # Test discovery
```

Artifacts are generated under `outputs/stage2/` and `outputs/stage3/`, ignored by Git.
Restart the API after training so it can load them. Missing or incompatible artifacts
are reported by `/api/health`; no inference values are fabricated. See
[`docs/detection.md`](docs/detection.md), [`docs/localization.md`](docs/localization.md),
and [`docs/api.md`](docs/api.md) for model and API details.

## Frontend scripts

```sh
npm run dev       # local dashboard
npm run typecheck # strict TypeScript check
npm run build     # production bundle in dist/
npm run preview   # preview the production bundle
```

## End-to-end demo checklist

1. **Confirm service/model health:** open any page and read the backend and model indicators in the header.
2. **Inspect the initial microgrid:** use System Overview for current state, telemetry, topology and events.
3. **Start a normal run:** in Live Simulation, choose Normal, set the seed/speed and press Start.
4. **Observe live operation:** watch the simulation clock, telemetry charts and component list update.
5. **Pause and resume:** use Pause and Resume; controls disable when their action is invalid.
6. **Prepare a fault scenario:** pause, choose a fault family, set severity, start tick and seed, then press Start to create and run that seeded scenario.
7. **Inject a fault into the current run:** choose a non-normal family, set severity/start tick and use Inject fault; the selected fault is backend ground truth, kept separate from predictions.
8. **Review a detected incident:** open Fault Investigation or Incident History to inspect the returned diagnosis, confidence, alternatives, evidence, timeline and suspected propagation paths.
9. **Apply a simulated correction:** use Apply simulated corrective action in the investigation view; this only changes the software simulation.
10. **Compare sustainability:** open Sustainability for directly simulated energy totals, the paired normal/faulty/corrected runs and calculation assumptions.
11. **Review model performance and export records:** Model Evaluation runs a real quick held-out evaluation when artifacts are loaded; Incident History exports the API records as CSV or JSON.

## Repository layout

```text
src/                  React dashboard, typed API service, hooks and UI components
backend/app/          FastAPI service, simulator, models, incidents and persistence
backend/tests/        Backend test suite
docs/                 API contract and subsystem methodology
scripts/              Local API verification helper
```
Only one fault can be active at a time. Disjoint scheduled faults are supported.
`step()` executes exactly one tick; no background loop or wall-clock sleep exists.
Direct library callers must serialize simulator access. The Stage 5 API supplies
this synchronization for HTTP requests. The physical simulator stays synchronous.

Simulation values are synthetic. Ground truth is available only for explicit
scenario/demo use; it is not used as model input. See [the API contract](docs/api.md)
and [simulation notes](docs/simulation.md) for units, limits and assumptions.
