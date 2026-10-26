# Stage 5 validation — 2026-10-26

Environment: Windows, Python 3.12.14, FastAPI 0.115.12, Pydantic 2.11.5,
Uvicorn 0.34.3, HTTPX 0.28.1 and the existing pinned simulation/ML stack.

```text
.\.venv\Scripts\python.exe -m pytest -q
145 passed, 1 warning in 46.07s
```

The warning is a Starlette TestClient reference to a deprecated AnyIO alias; it
does not affect test results. Dependency validation reported no broken requirements.
Windows asyncio requires a loopback socket pair, so API/async tests ran with local
network access outside the desktop filesystem/network sandbox.

## Automated coverage

All 119 prior tests still pass. The 26 new cases cover:

- Request validation, unknown fields, invalid physical config, unsupported fault
  modes and severities, integer limits, and no side effects on failed requests.
- Model-unavailable health/state, explicit 503 evaluation error, and absence of
  fabricated predictions/incidents when artifacts are missing.
- Deterministic reset, cursor pagination, historical telemetry and scenario counts.
- Concurrent/repeated Start calls sharing one worker; stable paused state; Resume
  reusing that worker; forbidden reset/manual Step while running; contiguous ticks.
- Scheduled fault overlap/past validation, correction, equal-horizon comparisons,
  separately labeled truth, and conserved energy.
- Incident creation with actual fitted models, details, graph, filters/search,
  timestamps, reset interruption, restart persistence and CSV/JSON exports.
- Real asynchronous held-out evaluation, duplicate-job conflicts, persisted results
  matched to artifact hashes after restart, automatic tick-limit pause and clean
  runner shutdown, plus SQLite crash-recovery scenario status.
- Daily total/renewable energy conservation across normal, sensor, controller,
  inverter and firmware runs; initial unknown battery provenance and null unused
  efficiency measurements.

Tick telemetry, changed incident reports, events and scenario/energy checkpoints
commit in one SQLite transaction. The tests exercise state consistency and history
retention; they are not multi-process deployment or long-duration load tests.

## Actual HTTP verification

A hidden local Uvicorn process was started on `127.0.0.1:8000` with the full saved
Stage 2/3 models. `scripts/verify_api.py` exercised actual HTTP routes rather than
only TestClient. It created a seed-42 inverter-derating scenario (severity 0.8,
start tick 30, duration 120), advanced 80 ticks, corrected it, and advanced 60 more.

One persisted incident was confirmed at tick 32, with representative Actuator/Inverter
hypothesis at tick 61 (uncalibrated score 0.9833693309). It resolved at tick 84 after
five quiet ticks. Graph evidence, incident export and live state endpoints succeeded.

| Directly simulated quantity, equal 140-tick horizon | Baseline | Faulty uncorrected | Operated with correction |
|---|---:|---:|---:|
| Solar generation (kWh) | 18.700065 | 18.700065 | 18.700065 |
| Demand served (kWh) | 13.262121 | 4.991854 | 9.474002 |
| Unmet demand (kWh) | 0.104084 | 8.374351 | 3.892203 |
| Final battery energy (kWh) | 18.920086 | 18.920086 | 18.920086 |

Estimated fault-associated delivery loss was 8.270268 kWh and correction-associated
delivery gain 4.482148 kWh. These are paired simulation counterfactual differences,
not measured real-world or causal savings. Total and renewable balance residuals
were below 3 × 10^-14 kWh. Initial unknown storage was not counted as renewable.

The HTTP quick evaluation completed and persisted actual results:

- Anomaly profile: 360 held-out normal ticks plus 600 active ticks across five clear
  fault modes; combined recall 99.67%, normal-tick false-positive rate 0%.
- Source profile: 50 complete held-out runs, 6,999 selected ticks; overall accuracy
  including Unknown 84.05%, coverage 90.18%, accepted accuracy 93.20%.

This narrower quick profile is a workflow check, not a replacement for the harder
full Stage 2/3 benchmarks. The model was neither retrained nor tuned to this run.
The server's model-metrics response labels profile and report provenance.

After a process restart with the final code, the prior resolved incident remained
queryable, a new paused live run started at tick zero, and the same HTTP demo
reproduced the energy totals above. The final live run is paused at tick 140.
Machine-recorded results are in [stage5-example.json](stage5-example.json); local
SQLite/log files remain under ignored `outputs/server`.

## Remaining stages

Stage 5 is complete. **Two stages remain:** Stage 6, the React/Vite dashboard and
frontend integration; Stage 7, final held-out evaluation, complete UI/demo checks
and final documentation. No dashboard or frontend integration tests are claimed
at this stage. API/local-service limits are documented in [api.md](api.md), and
energy assumptions in [sustainability.md](sustainability.md).
