# TraceX GreenGrid — Project Status

## Purpose and constraints

Software-only renewable microgrid simulation and fault-localization prototype for a
student hackathon. Keep the Stage 1 simulator API, physics, energy accounting,
deterministic seeding, single-active-fault semantics, and offline exports intact.
Python 3.11 or 3.12 is supported. No hardware, paid service, or external runtime API
is required. Scenario ground truth must stay separate from telemetry and inference.
No sustainability attribution or AI performance claims are supported by this project.

## Verified current state

Repository was inspected at commit `ef217f8` (`Database and API Implementation`) on
branch `backend`; current changes implement the AI integration contract and adapter.
Before this turn's changes the worktree contained only the status document and its
Stage 1 validation correction. The available
conversation history confirms the preceding repository audit, API implementation,
and persistence implementation requests. No further numbered prompt was supplied in
this turn; the next work must be selected by the user's next prompt.

### Stack and structure

- Python, existing Stage 1 simulator and fault-injection code, NetworkX topology.
- FastAPI API under `/api/v1`; Pydantic typed contracts and structured errors.
- SQLAlchemy 2, PostgreSQL via psycopg, and Alembic migrations.
- Managed JSONL telemetry artifacts and JSON topology artifacts; SQL rows contain
  indexed artifact metadata, replay commands, and compact summaries.
- SQLite is used by isolated tests. It is not the configured production database.

## Implemented features

- **Stage 1 simulation:** physical tick model, validated configuration, deterministic
  fault schedules, communication/controller behavior, propagation topology, CLI, and
  offline CSV/JSON exports. See `backend/app/{simulator,fault_injection,propagation}`.
- **HTTP API:** health/readiness, fault catalog, run creation/status/advance,
  scheduling/correction, telemetry/controller logs, topology/downstream, result
  metadata, authorized CSV/JSON downloads, and authorized incident CRUD with filters
  and pagination. See `backend/app/api` and `docs/api.md`.
- **Persistence:** run, fault scenario, command journal, result metadata, incident,
  and AI analysis records; foreign keys, checks, indexes, and an additive initial
  migration. Run state is replayed from the ordered action journal on startup.
  See `backend/app/persistence` and `backend/migrations`.
- **AI integration:** provider-independent typed request/response protocol, generic
  HTTP adapter, optional local adapter injection point, bounded in-process jobs,
  idempotency keys, validated results, and analysis status/result endpoints. No AI
  team's actual provider or model is present/configured; the default provider returns
  unavailable and never fabricates output. Mocked provider tests are fixtures only.
- **Ground-truth isolation:** scenario records are not emitted as normal API result or
  incident data; incident evidence rejects reserved ground-truth keys. AI-specific
  DTOs also omit simulator-only PV reference, physical-state, energy-balance, and
  firmware-integrity oracle fields. The CLI still writes its separate
  `scenario_ground_truth.json` for offline use.

## Configuration and commands

Environment variable names are documented in `.env.example`; it contains placeholders
only. The application reads process environment variables and does not load `.env`
automatically:

- `TRACEX_ENV`, `TRACEX_CORS_ORIGINS`
- `TRACEX_DATABASE_URL` (PostgreSQL SQLAlchemy URL)
- `TRACEX_DATA_DIR`
- `TRACEX_EXPORT_API_KEY`, `TRACEX_INCIDENT_API_KEY`
- `TRACEX_AI_SERVICE_URL`, `TRACEX_AI_SERVICE_API_KEY`, `TRACEX_AI_TIMEOUT_SECONDS`,
  `TRACEX_AI_MAX_RETRIES`, `TRACEX_AI_WORKERS`, `TRACEX_AI_QUEUE_SIZE`

From the repository root on Windows, after creating `.venv` and installing the pinned
requirements:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
$env:PYTHONPATH = 'backend'
$env:TRACEX_DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@localhost:5432/tracex_greengrid'
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

The migration command requires a reachable PostgreSQL database and is documented,
but has not been verified against a live PostgreSQL server in the available session.
The automated migration test runs Alembic against a temporary SQLite database.
Never reset or drop a database to apply migrations.

## Verification and limitations

- Full suite in the current AI integration turn: **99 passed**, one Starlette/AnyIO
  `BlockingPortal` deprecation warning. This includes Stage 1, API, persistence,
  restart/migration, and mocked AI integration tests. Environment: Python 3.12.14 and
  pinned requirements. Provider tests use local `httpx.MockTransport` and test
  fixtures, not a paid endpoint or model evaluation.
- No live PostgreSQL server was available; PostgreSQL-specific runtime behavior still
  needs environment verification.
- Simulator locks and restored simulator instances are process-local. The documented
  API deployment is single-worker only until cross-process locking/leases are added.
- Incident categories and priorities are caller-supplied text; the repository defines
  no taxonomy or priority scale. Other routes are not tenant-authenticated.
- There is no frontend/dashboard, model, anomaly detector, or validated localization
  accuracy measurement.
- The AI request/response contract is a proposed v1 agreement because no team
  interface was available in the repository. Confirm its field semantics, output
  meaning, authentication, and HTTP endpoint path with the AI teammates before
  deploying against their service. Real inference remains unavailable until then.
- Jobs run in a bounded in-process thread pool; a process restart marks unfinished
  jobs failed. A durable external queue is not implemented.

## Documentation

- `README.md`: project setup and structure.
- `docs/simulation.md`: simulator equations and semantics.
- `docs/stage1-validation.md`: original Stage 1 test/demo record.
- `docs/api.md`: API endpoints, persistence, migrations, security, and limitations.
- `docs/ai-integration.md`: AI provider contract, payload schemas, and connection steps.

The next recommended action is to confirm the proposed AI contract with the AI team
and connect their real local adapter or HTTP service once its interface and deployment
are available. No model quality or localization accuracy has been measured.
