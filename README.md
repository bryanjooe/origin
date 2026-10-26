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

On macOS/Linux use `.venv/bin/python` and `export PYTHONPATH=backend`.
In this Codex workspace the virtual environment was bootstrapped with the bundled
Python 3.12 runtime because the Windows `python` alias is unavailable. The commands
using `.venv\Scripts\python.exe` work directly here.

Outputs include `telemetry.csv`, `telemetry.json`, `topology.json`, and a **separate**
`scenario_ground_truth.json`. Keep the latter out of future inference features.
The printed totals are directly integrated physical simulation quantities, not
sustainability attribution, ML evaluation, or estimated carbon savings.

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

## Library use

```python
from app.simulator import MicrogridSimulator, GridConfig

sim = MicrogridSimulator(GridConfig(start_hour=17), seed=42)
sim.run(10)
sim.inject("sensor", "bias", severity=0.8, duration_ticks=20)  # Starts now
rows = sim.run(10)
sim.correct()  # Restores components; preserves battery energy and simulation time
sim.run(20)
sim.reset()    # Clears history and schedules; restores original seeded RNG state
```

Only one fault can be active at a time. Disjoint scheduled faults are supported.
`step()` executes exactly one tick; no background loop or wall-clock sleep exists.
Direct library callers must serialize simulator access. The Stage 5 API supplies
this synchronization for HTTP requests. The physical simulator stays synchronous.

See [simulation documentation](docs/simulation.md) for fault modes, field semantics,
energy accounting, graph limitations, and the next-stage boundary.
