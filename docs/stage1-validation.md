# Stage 1 validation — 2026-10-26

Environment: Windows, Python 3.12.14, NetworkX 3.4.2, pytest 8.3.5.

```text
.\.venv\Scripts\python.exe -m pytest -q
72 passed in 2.19s
```

Coverage includes all 16 implemented fault modes, two simulated days of energy
balance, battery boundary conditions at 1/60/3600-second intervals, normal control,
communication freshness and startup fail-safe behavior, scheduling, correction,
reset, deterministic replay, ground-truth separation, graph traversal, input
validation and command-line export round trips. These are automated simulation
tests, not real-world validation or model-performance measurements.

The first export-test attempt encountered restricted OS temporary-directory
permissions. Export tests now use disposable directories within `outputs/test-temp`
so the standard test command also works in this workspace sandbox.

## Reproducible demo

Both scenarios used seed 42, default configuration and 180 one-minute ticks.
The inverter scenario used derating severity 0.8 starting at tick 30, planned
duration 120 ticks, and simulated correction at tick 110.

| Directly simulated quantity | Normal | Inverter fault, then correction |
|---|---:|---:|
| PV generation (kWh) | 24.140820 | 24.140820 |
| Demand served (kWh) | 16.989719 | 10.957579 |
| Unmet demand (kWh) | 0.130998 | 6.163137 |
| Final battery SOC (%) | 84.893009 | 84.893009 |

Average delivered power in the fault/correction run: 5.8112 kW during ticks 0–29,
1.1409 kW during ticks 30–109, and 5.5979 kW during ticks 110–179. These periods
have different demand and sunlight, so phase averages are not a controlled
fault-attribution estimate. Normal operation has small unmet demand because noisy
measurements can slightly under-request inverter output; normal does not mean a
perfect clairvoyant controller.

These particular inverter faults leave battery dispatch unchanged, explaining the
matching final SOC. Outputs are saved locally in `outputs/normal` and
`outputs/inverter`, each containing telemetry CSV/JSON, topology JSON, and a separate
scenario-truth file retaining the correction tick.

Stages 2–7 were not started. No anomaly-detection or localization accuracy is
claimed. No API, frontend or persistence behavior is implied by these tests.
