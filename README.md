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

The backend reads `ORIGIN_*` settings from the process environment. Existing
`TRACEX_*` names remain accepted for compatibility with earlier scripts.

## Train the optional ML models

The simulation and operational controls work without trained models. The dashboard
will show model predictions and held-out evaluation as unavailable until the model
artifacts exist. To enable those features, train both models from the repository root:

```sh
PYTHONPATH=backend .venv/bin/python -m app.detection
PYTHONPATH=backend .venv/bin/python -m app.localization
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

Simulation values are synthetic. Ground truth is available only for explicit
scenario/demo use; it is not used as model input. See [the API contract](docs/api.md)
and [simulation notes](docs/simulation.md) for units, limits and assumptions.
