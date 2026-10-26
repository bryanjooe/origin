# TraceX GreenGrid backend setup and deployment

This backend runs on Python 3.11 or 3.12. Runtime dependencies are pinned in
`backend/requirements.txt`. The API uses FastAPI and Uvicorn, PostgreSQL through
SQLAlchemy/psycopg, and Alembic migrations. Docker is optional; the application has
no Docker dependency.

## Create an environment

Run these commands from the repository root. Choose Python 3.11 or 3.12 explicitly
if the system's `python` command points to another version.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
$env:PYTHONPATH = 'backend'
```

### macOS or Linux

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r backend/requirements.txt
export PYTHONPATH=backend
```

`pyproject.toml` configures pytest discovery and the backend import path.

## Configure the database and secrets

Copy `.env.example` for reference, then set the values in the process environment or
your deployment's secret manager. The application does **not** load `.env` files
automatically. Create the PostgreSQL database and database role through the normal
administration workflow. Use a PostgreSQL connection URL in
`TRACEX_DATABASE_URL`; do not put a real password in source control or this document.

Set at least:

- `TRACEX_ENV=development` locally, or `production` in deployment.
- `TRACEX_DATABASE_URL` to the PostgreSQL connection URL.
- `TRACEX_DATA_DIR` to durable storage that is not served publicly.
- `TRACEX_API_TOKENS` to a JSON object mapping random bearer tokens (at least 32
  characters in production) to stable principal IDs. Keep this value secret.
- `TRACEX_CORS_ORIGINS` to the exact frontend origin(s), comma-separated. For local
  frontend development the template lists `http://localhost:3000` and
  `http://127.0.0.1:3000`. The repository contains no frontend application, so replace
  these with the origin the frontend team actually deploys, including scheme and
  port where applicable. Do not use `*` in production.

Optional `TRACEX_AI_*` settings configure the separate AI adapter. Empty
`TRACEX_AI_SERVICE_URL` means inference is unavailable; no result is fabricated.
Other bounds and settings are described in [the API reference](api.md).

## Apply migrations and run checks

Migrations preserve existing data. Do not reset the database to install the schema.

```powershell
$env:PYTHONPATH = 'backend'
$env:TRACEX_DATABASE_URL = '<PostgreSQL SQLAlchemy URL from the environment>'
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m pytest -q
```

macOS/Linux equivalent:

```sh
export PYTHONPATH=backend
.venv/bin/python -m alembic -c backend/alembic.ini upgrade head
.venv/bin/python -m pytest -q
```

The automated migration and restart tests use SQLite. Run `upgrade head` against the
configured PostgreSQL database in each deployment environment before starting the
API; a successful SQLite test does not verify PostgreSQL connectivity or operations.

## Local application startup

For local development, keep the API bound to loopback:

```powershell
$env:PYTHONPATH = 'backend'
$env:TRACEX_ENV = 'development'
$env:TRACEX_DATABASE_URL = '<PostgreSQL SQLAlchemy URL>'
$env:TRACEX_DATA_DIR = '.\data'
$env:TRACEX_CORS_ORIGINS = 'http://localhost:3000,http://127.0.0.1:3000'
$env:TRACEX_API_TOKENS = '{"<random-local-token-of-32-characters-or-more>":"local-operator"}'
.\.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

Equivalent macOS/Linux startup:

```sh
export PYTHONPATH=backend
export TRACEX_ENV=development
export TRACEX_DATABASE_URL='<PostgreSQL SQLAlchemy URL>'
export TRACEX_DATA_DIR=./data
export TRACEX_CORS_ORIGINS='http://localhost:3000,http://127.0.0.1:3000'
export TRACEX_API_TOKENS='{"<random-local-token-of-32-characters-or-more>":"local-operator"}'
.venv/bin/python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

## Production server

Uvicorn is the configured ASGI server. Run a **single worker**: live simulator
instances, per-run locks, analysis workers, and rate-limit counters are process-local.
Put a TLS-terminating reverse proxy or platform ingress in front of the service and
restrict forwarded-header trust to that proxy's actual address. For example, on
Linux behind a proxy at the shown placeholder address:

```sh
export PYTHONPATH=backend
export TRACEX_ENV=production
# Set database URL, data directory, exact CORS origin(s), token map and optional AI
# settings through the deployment environment or secret manager.
.venv/bin/python -m uvicorn app.api.main:app \
  --host 0.0.0.0 --port 8000 --workers 1 \
  --proxy-headers --forwarded-allow-ips='<trusted-proxy-address>'
```

Do not increase `--workers` until simulator coordination and rate limiting use shared
cross-process state. Store `TRACEX_DATA_DIR` on durable storage shared by the app
instance across restarts. Cloud deployment has not been performed or verified here.

## Health, OpenAPI, and smoke check

- `GET /api/v1/health/live` reports that the API process is serving.
- `GET /api/v1/health/ready` returns ready only when startup replay succeeded and the
  database remains reachable.
- `GET /api/v1/health/dependencies` reports API status, live database connectivity,
  and AI configuration. AI status is `not_configured` or `configured_unverified`.
  No health endpoint was agreed with the AI team, so configured AI reachability is
  not actively probed and does not block API readiness.
- OpenAPI JSON is at `/openapi.json`; interactive Swagger docs are at `/docs` and
  ReDoc is at `/redoc`.

With migrations applied, database and API tokens configured, run the repeatable
end-to-end smoke flow. It creates and retains one run, advances three ticks, reads
status/telemetry/result metadata, starts a fresh application instance, then verifies
those records are still available:

Run this against an isolated or staging database, or while the API is stopped and
the database is otherwise idle. Application startup marks unfinished in-process AI
jobs as interrupted, and multiple service processes are not supported.

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m app.smoke_test
```

macOS/Linux:

```sh
export PYTHONPATH=backend
.venv/bin/python -m app.smoke_test
```

## Feature status

- **Implemented:** existing synchronous simulator and CLI, deterministic fault
  injection, topology propagation, persistent runs and telemetry artifacts, incidents,
  authenticated owner-scoped API, authorized exports, and database migration/replay.
- **AI integration:** typed provider contract and bounded HTTP adapter/job lifecycle
  exist. Actual analysis requires the AI team's compatible service and deployment
  settings. The health endpoint reports its configuration, not live reachability.
- **Unavailable:** dashboard/frontend in this repository, trained model, inference
  accuracy claims, durable distributed job queue, and multi-worker simulator locking.
- **Not verified here:** live PostgreSQL deployment, production proxy/TLS setup, and
  cloud deployment.

The original CLI workflow and offline CSV/JSON exports remain available. See
[`docs/simulation.md`](simulation.md) for simulator behavior and [`docs/api.md`](api.md)
for endpoint schemas and examples.
