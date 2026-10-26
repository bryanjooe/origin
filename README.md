# TraceX GreenGrid

Software-only renewable microgrid fault-localization project. **Stage 1 only is
implemented and tested:** physical simulation, deterministic fault injection,
timestamped communication, controller logs, dependency topology, and offline exports.
There is no trained model, anomaly detector, web server, dashboard, or incident
database yet. No AI predictions or performance metrics are produced.

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

## Structure

```text
backend/
  app/
    simulator/          # Validated immutable config, physical model, CLI
    fault_injection/    # Fault families, validated schedules, scenario truth
    propagation/        # NetworkX dependency graph and downstream traversal
  tests/                # Deterministic physics, faults, graph, export checks
  requirements.txt
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
Callers must serialize simulator access. Start/pause/resume synchronization belongs
to the future API stage. Methods are intentionally synchronous in Stage 1.

See [simulation documentation](docs/simulation.md) for fault modes, field semantics,
energy accounting, graph limitations, and the next-stage boundary.
