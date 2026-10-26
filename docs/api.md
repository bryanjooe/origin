# TraceX GreenGrid HTTP API

The API is a FastAPI layer around the Stage 1 simulator and propagation modules.
PostgreSQL stores run definitions, restricted fault-scenario records, action history,
incident records, analysis records, and result metadata. Telemetry and topology
artifacts live in the configured managed data directory. There is no trained model,
anomaly detector, dashboard, or scenario-ground-truth endpoint.

## Run locally

Install the pinned requirements from the repository root, set the backend import
path, then run Uvicorn:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
$env:PYTHONPATH = 'backend'
$env:TRACEX_DATABASE_URL = 'postgresql+psycopg://tracex_user:CHANGE_ME@localhost:5432/tracex_greengrid'
$env:TRACEX_DATA_DIR = './data'
$env:TRACEX_CORS_ORIGINS = 'http://localhost:3000,http://127.0.0.1:3000'
$env:TRACEX_EXPORT_API_KEY = 'set-a-private-value-before-starting-the-server'
$env:TRACEX_INCIDENT_API_KEY = 'set-a-different-private-value-before-starting-the-server'
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

The application reads settings from process environment variables. `.env.example`
documents their names; the API does not load `.env` files automatically.
Interactive OpenAPI documentation is available at `/docs` while the server is
running.

## Settings and security

| Variable | Behavior |
| --- | --- |
| `TRACEX_ENV` | `development` by default. Setting it to `production` rejects wildcard CORS origins. |
| `TRACEX_CORS_ORIGINS` | Comma-separated exact origins. Defaults to no CORS origins in every environment. |
| `TRACEX_DATABASE_URL` | SQLAlchemy URL for PostgreSQL, e.g. `postgresql+psycopg://user:password@host:5432/database`. No credential is embedded in the application default. |
| `TRACEX_DATA_DIR` | Managed artifact root. Defaults to `./data`; keep it on durable storage and outside public web roots. |
| `TRACEX_EXPORT_API_KEY` | Server-side bearer key required for result downloads. If unset, downloads return 503. |
| `TRACEX_INCIDENT_API_KEY` | Independent bearer key required for incident CRUD. If unset, incident routes return 503. |
| `TRACEX_AI_SERVICE_URL` | Optional separately deployed model service base URL. Unset disables inference and produces failed `provider_unavailable` jobs. |
| `TRACEX_AI_SERVICE_API_KEY` | Optional bearer credential sent only to the configured AI provider. |
| `TRACEX_AI_TIMEOUT_SECONDS` | Per-call timeout; defaults to 10 seconds and is capped at 120. |
| `TRACEX_AI_MAX_RETRIES` | Bounded retries for transient transport errors, HTTP 408/429, and 5xx; defaults to 1 and is capped at 3. |
| `TRACEX_AI_WORKERS`, `TRACEX_AI_QUEUE_SIZE` | In-process analysis worker and queue bounds; defaults to 2 workers and 8 queued jobs. |

The API returns `Authorization: Bearer <key>` credentials only as request headers;
they are never echoed in responses. Store the key in the server environment or a
secret manager. Do not commit a populated `.env` file. Other API routes currently
have no authentication or tenant isolation and should remain on a trusted local
network until those controls are added. Incident routes use the dedicated incident
key; export downloads use the export key. Neither is returned by the API.

Errors use this shape and omit rejected input values and internal exception detail:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "request_id": "...",
    "details": [{"location": "body.config.tick_seconds", "message": "Input should be greater than 0", "type": "greater_than"}]
  }
}
```

## Endpoints

All application routes are under `/api/v1`.

| Method and path | Contract |
| --- | --- |
| `GET /health/live` | Process liveness. |
| `GET /health/ready` | Database schema and run replay readiness. |
| `GET /fault-types` | Existing families/modes and the simulator's severity, duration, and start-tick constraints. |
| `POST /runs` | Create a run with optional complete `GridConfig` fields, integer seed, and optional initial fault schedule. Returns 201. |
| `GET /runs/{run_id}` | Run status, current tick, config, timestamps, and bounds. |
| `POST /runs/{run_id}/analyses` | Submit an asynchronous analysis of an available tick window; requires an `Idempotency-Key`; returns 202 and an analysis job ID. |
| `GET /analyses/{analysis_id}` | Retrieve job status, timestamps, model metadata, sanitized failure or validated result. |
| `POST /runs/{run_id}/advance` | Advance 1–1,000 ticks synchronously in the server worker pool. A run is capped at 10,000 total ticks. |
| `POST /runs/{run_id}/fault-schedules` | Add a fault at or after the current tick. Uses existing validation and rejects overlapping schedules. |
| `POST /runs/{run_id}/correct` | Apply the simulator's correction semantics at the current serialized boundary. |
| `GET /runs/{run_id}/telemetry` | Read typed telemetry for `[start_tick, end_tick)`. Defaults to all available ticks; at most 2,000 per response. |
| `GET /runs/{run_id}/controller-logs` | Read typed controller logs using the same range rules. |
| `GET /topology` | Existing dependency graph, including node labels and edge metadata. |
| `GET /topology/{component}/downstream` | Existing sorted descendants; unknown components return 404. |
| `GET /runs/{run_id}/exports` | Metadata for on-demand JSON and CSV telemetry exports. No local paths or credentials. |
| `GET /runs/{run_id}/results` | Stored artifact metadata and compact output summary; paths and scenario truth are omitted. |
| `GET /runs/{run_id}/exports/{format}` | Download CSV or JSON for a tick range. Requires configured bearer authorization; at most 10,000 ticks. |
| `POST /incidents` | Create an authorized incident with a topology component, caller-provided category/evidence, optional run, and optional priority. |
| `GET /incidents` | Authorized list with page/page_size (max 100) and status, category, component, and run filters. |
| `GET /incidents/{incident_id}` | Retrieve one authorized incident. |
| `PATCH /incidents/{incident_id}` | Update caller-provided incident fields and investigation status. History is preserved; there is no delete route. |

Tick ranges are half-open and must satisfy `0 <= start_tick <= end_tick <= current_tick`.
Invalid configuration or fault parameters return 422; overlapping fault schedules
return 409; a missing run/component returns 404; unauthorized downloads return 401.
If the export key is not configured, download attempts return 503. Unexpected
failures return a generic 500 with a request ID; details are logged server-side.
Incident routes return 401 for missing/invalid authorization and 503 when their
key is not configured. Categories and priorities are caller-provided text because
the repository defines no incident taxonomy or priority scale.

## Example

```powershell
$env:TRACEX_EXPORT_API_KEY = 'set-a-private-value-before-starting-the-server'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/runs `
  -ContentType 'application/json' -Body '{"seed":42,"config":{"start_hour":17.0}}'
```

The create response includes an opaque `run_id`. Advance with
`POST /api/v1/runs/{run_id}/advance` and body `{"ticks": 180}`, then read telemetry
or controller logs. Downloads require `Authorization: Bearer $env:TRACEX_EXPORT_API_KEY`.

## Persistence, migrations, and data boundaries

Apply migrations before starting the API:

```powershell
$env:PYTHONPATH = 'backend'
$env:TRACEX_DATABASE_URL = 'postgresql+psycopg://tracex_user:CHANGE_ME@localhost:5432/tracex_greengrid'
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
```

Create the PostgreSQL database and role through your approved local PostgreSQL
administration workflow, then provide the connection string through the environment.
The migration is additive and deliberately has no destructive downgrade. Never put a
real password in `.env.example` or commit a populated `.env` file.

The schema includes `simulation_runs`, restricted `fault_scenarios`, an ordered
`simulation_commands` replay journal, `simulation_result_metadata`, `incidents`, and
`ai_analysis_records`. Foreign keys use `ON DELETE RESTRICT`; schedules, commands,
results, and incidents are not deleted by the API. Scenario parameters live only in
the fault table and replay journal. They are not included in telemetry, result
metadata, incident evidence, or API responses.

Telemetry is stored as append-only JSON Lines chunks under the managed data directory,
with indexed tick ranges, hashes, byte sizes, and relative storage references in the
database. Controller logs are projections over telemetry chunks rather than duplicate
large rows. Topology snapshots are small managed JSON artifacts; output summaries are
compact structured database metadata. API responses never expose absolute paths.

The database stores no incident severity scale because none exists in the project;
`priority` and `category` remain caller-supplied text. AI analysis records distinguish
no record (missing), `pending`, `running`, `failed`, and `completed`. Completed output
passes a typed schema validator before persistence. No model from the AI team is
present in this repository; use the documented adapter contract in
`docs/ai-integration.md`. When no AI provider is configured, analysis jobs fail with
`provider_unavailable`, and no prediction is fabricated.

Incident evidence rejects reserved ground-truth field names recursively and is size
bounded. The analysis service accepts only the typed analysis output contract. It has
no method that reads fault scenario tables as inference input.

The provider-independent input adapter sends only a typed telemetry window and
matching controller-log projection, capped at 2,000 ticks and frozen at submission.
Ground truth, hidden labels, fault schedules, simulator events, and future ticks are
excluded. Analysis work runs in a bounded in-process worker pool and is idempotent via
the required `Idempotency-Key`. A restart marks unfinished in-process jobs failed.
Provider credentials and retry/timeout/queue limits use `TRACEX_AI_*` environment
settings; see `docs/ai-integration.md` for schemas, retries, and unresolved team
interface decisions.

## Concurrency and persistence boundaries

Each run has its own lock. All operations that read or mutate its simulator state
hold that lock; separate runs can proceed independently. Synchronous simulator work
runs in FastAPI's worker pool and is bounded by per-request and per-run tick limits.
The measured simulator runtime was approximately 0.135 seconds for 10,000 ticks on
the audit host; this is an environment measurement, not a latency guarantee.

Run definitions and action journals persist. On startup the service recreates each
simulator by replaying its validated config, seed, fault-control actions, advances, and
corrections; the simulator implementation itself remains unchanged. Telemetry files
and metadata remain available after restart. In-process locks serialize each run,
but multiple API worker processes are not supported because run locks and live
simulators are process-local. Use one API worker until a database-backed lease/lock is
added. The API never returns `FaultEngine.ground_truth()`, fault records, or the CLI's
`scenario_ground_truth.json`.
