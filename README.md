# TraceX GreenGrid

Software-only renewable microgrid fault-localization project. Stage 1 provides the
physical simulator, deterministic fault injection, timestamped communication,
controller logs, dependency topology, and offline exports. Stage 2 adds a versioned
FastAPI layer with PostgreSQL persistence for runs, incidents, and result metadata,
plus a provider-independent integration contract for a separately developed AI
component. No team model is currently connected, so no AI predictions, anomaly
detector, dashboard, or performance metrics are produced.

## Setup

Python 3.11 or 3.12. The simulator requires no hardware, external API, or paid
service. An optional AI adapter can connect to a separately deployed model service.
Installation needs PyPI access; simulation and tests run offline after installation.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
$env:PYTHONPATH = 'backend'
$env:TRACEX_ENV = 'development'
$env:TRACEX_DATABASE_URL = 'postgresql+psycopg://tracex_user:CHANGE_ME@localhost:5432/tracex_greengrid'
$env:TRACEX_CORS_ORIGINS = 'http://localhost:3000,http://127.0.0.1:3000'
$env:TRACEX_API_TOKENS = '{"<random-local-token-of-32-characters-or-more>":"local-operator"}'
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m pytest -q
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m app.simulator --fault normal --output outputs/normal
.\.venv\Scripts\python.exe -m app.simulator --fault inverter --mode derate --severity 0.8 --start 30 --duration 120 --correct-at 110 --output outputs/inverter
.\.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

On macOS/Linux use `.venv/bin/python` and `export PYTHONPATH=backend`.
In this Codex workspace the virtual environment was bootstrapped with the bundled
Python 3.12 runtime because the Windows `python` alias is unavailable. The commands
using `.venv\Scripts\python.exe` work directly here.

Outputs include `telemetry.csv`, `telemetry.json`, `topology.json`, and a **separate**
`scenario_ground_truth.json`. Keep the latter out of future inference features.
The printed totals are directly integrated physical simulation quantities, not
sustainability attribution, ML evaluation, or estimated carbon savings.

## Structure

```text
backend/
  app/
    simulator/          # Validated immutable config, physical model, CLI
    fault_injection/    # Fault families, validated schedules, scenario truth
    propagation/        # NetworkX dependency graph and downstream traversal
    api/                # FastAPI routes, typed schemas, settings, errors, services
    persistence/        # PostgreSQL entities, repository, managed result files
    smoke_test.py       # Authenticated run/restart/persistence smoke flow
  migrations/           # Additive Alembic schema migrations
  tests/                # Simulator, faults, graph, exports, and API checks
  requirements.txt
docs/simulation.md      # Equations, units, and limitations
docs/api.md             # API, persistence, migrations, and environment settings
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
The API serializes access per run and advances in bounded requests; simulator methods
remain synchronous.

See [simulation documentation](docs/simulation.md) for fault modes, field semantics,
energy accounting, graph limitations, and the next-stage boundary. See
[API documentation](docs/api.md) for endpoints, schemas, OpenAPI, and examples. See
[deployment instructions](docs/deployment.md) for reproducible environment setup,
production Uvicorn startup, health checks, and the persistence smoke test. Copy
`.env.example` for available settings; the API reads them from process environment
variables and does not load the file automatically.
