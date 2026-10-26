# TraceX GreenGrid

Software-only renewable microgrid fault-localization project. **Stages 1–3 are
implemented:** physical simulation, deterministic fault injection, timestamped
communication, controller logs, dependency topology, and a normal-baseline
Isolation Forest anomaly detector with separately labeled residual checks, and a
Random Forest source classifier with confidence-based abstention.
There is no web server, dashboard, or incident database yet.

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

## Structure

```text
backend/
  app/
    simulator/          # Validated immutable config, physical model, CLI
    fault_injection/    # Fault families, validated schedules, scenario truth
    propagation/        # NetworkX dependency graph and downstream traversal
    detection/          # Causal features, normal-only ML, calibration, evaluation
    localization/       # Supervised source classifier, confidence/Unknown, evaluation
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
