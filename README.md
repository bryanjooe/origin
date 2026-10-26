# Origin

Origin is a front end for observing a simulated renewable microgrid and reviewing fault-localization results. Simulation values, predictions, evidence, and evaluation metrics are only displayed when returned by the API. The interface does not control physical equipment.

## Frontend setup

Requirements: Node.js 22.12+ and npm. Start the separate FastAPI backend on `http://127.0.0.1:8000`, then run the frontend from the repository root:

```sh
npm install
npm run dev
```

Vite serves the app at `http://127.0.0.1:5173` and proxies `/api` and `/ws` to the local backend. The static production build is created in `dist/`:

```sh
npm run typecheck
npm run build
npm run preview
```

The simulation engine in `backend/` is the project’s Stage 1 Python simulator. It does not itself implement the FastAPI endpoints below; run the separately specified API service for live data and actions.

## Environment variables

Copy `.env.example` to `.env.local` as needed.

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | empty | Empty uses Vite’s local proxy. Set to the API origin (for example `http://127.0.0.1:8000`) when serving the frontend elsewhere. |

## API contract assumptions

All endpoints are typed centrally in `src/services/api.ts`; shapes live in `src/types/domain.ts`. Responses may omit optional values. Missing values render as unknown or unavailable, never as fabricated zeros. The API should return JSON arrays for telemetry, events, and incident lists; a topology object with `nodes` and optional `edges`; and the named fields documented by the TypeScript interfaces. The telemetry WebSocket is assumed at `/ws/telemetry`, accepting individual telemetry points or arrays (optionally wrapped in `data` or `telemetry`). If it is unavailable, the client polls `GET /api/telemetry` and reconnects with backoff.

The brief does not specify routes or schemas for changing run speed or applying a correction. The UI assumes `POST /api/simulation/speed` with `{ "speed": number }` and `POST /api/simulation/correct` with `{ "incident_id": string | number }`. It assumes `POST /api/model/evaluate` returns metrics synchronously. `POST /api/simulation/start` receives `{ scenario, seed, speed }`; `scenario` sends `inverter` for the UI’s Actuator / inverter option. Fault injection sends `{ scenario, severity, start_tick, seed }`. Export uses `GET /api/reports/export?format=csv|json`, returned as a downloadable response body. Adjust these single-point assumptions in `src/services/api.ts` if the separately specified backend uses different paths or payload keys.

Ground truth is displayed only when an incident response provides `ground_truth`; it is visually distinct from model predictions. Suspected graph links remain separate from known dependencies. Sustainability values carry the API’s estimate flag or the `estimated_loss_kwh` field label. Evaluation labels refer to held-out simulation scenarios.

## Demo workflow mapped to the UI

The task brief asks for an 11-step demo checklist but does not include the steps themselves. This practical checklist maps common demo actions to the available controls; rename or reorder it to match the backend’s official demo script.

1. **Check service readiness** — open **System overview** and inspect backend/model health in the top bar.
2. **Review the baseline microgrid** — inspect KPI values, power charts, topology, and recent events on **System overview**.
3. **Choose a scenario and seed** — open **Live simulation**, select Normal or a fault family, set the random seed and speed.
4. **Start the run** — use **Start**; the simulation clock and telemetry should update from the API.
5. **Pause or resume time** — use **Pause** and **Resume** as enabled by the current run state.
6. **Inject a fault** — select a non-normal scenario, set severity and start tick, then use **Inject fault**.
7. **Inspect component response** — review the live telemetry and component status list; then return to **System overview** for charts and recent events.
8. **Investigate an incident** — open **Fault investigation**, choose an incident, review evidence and candidate confidence, and select graph nodes for their telemetry/events.
9. **Apply a simulated correction** — use **Apply simulated corrective action** on an incident; the control is explicitly simulation-only.
10. **Compare energy outcomes** — open **Sustainability** to review returned normal/faulty/after-correction comparison and assumptions.
11. **Export and evaluate** — use **Incident history** filters and CSV/JSON export, then open **Model evaluation** to inspect held-out metrics or run evaluation.

## Project structure

```text
src/
  components/       shared UI, shell, charts, topology graph
  hooks/            API resource and telemetry streaming hooks
  pages/            overview, simulation, investigation, sustainability, incidents, evaluation
  services/api.ts   typed HTTP and WebSocket access
  types/            API domain types
  utils/            telemetry and metric formatting
backend/            simulator and supporting Python modules
docs/               simulator documentation
```

## Simulator notes

The Python simulator is synchronous and hardware-free. It produces synthetic signals. Its CLI and physical model documentation remain in `docs/simulation.md`; the frontend consumes the separate FastAPI service described above.

For a local Python simulator run, install its requirements and invoke the CLI from the repository root:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements.txt
PYTHONPATH=backend python -m app.simulator --fault inverter --mode derate --severity 0.8 --start 30 --duration 120 --correct-at 110 --output outputs/inverter
```
