# Stage 4 validation — 2026-10-26

Environment: Windows, Python 3.12.14, existing pinned NetworkX/scikit-learn stack.
No new runtime dependencies or model retraining were required.

```text
.\.venv\Scripts\python.exe -m pytest -q
119 passed in 22.05s
```

The 18 new tests cover warning confirmation, immediate critical incidents, recovery,
quiet-gap grouping, separate incidents after resolution, scarcity not opening
incidents, numeric explanations, absent source models, Unknown/conflicting Normal
predictions, graph evidence references, unchanged known dependencies, node details,
sensor ambiguity, feedback-cycle traversal, copied causal snapshots, reset,
ground-truth/oracle exclusion, input validation, CLI model requirements and real
saved-model integration. All 101 previous tests still pass.

Unit tests deliberately use explicit test-only model outputs for lifecycle edge
cases. The integration test trains real models, loads their saved artifacts, and
checks that incident diagnoses match actual representative-tick predictions,
including legitimate Unknown results rather than overriding model uncertainty.

## Measured demos using the saved full Stage 2/3 models

Both demos used seed 42, 180 one-minute ticks, severity 0.8, fault start tick 30,
planned duration 120 ticks, and simulated correction at tick 110. Hidden scenario
truth was exported separately and was not provided to the incident tracker.

| Observed incident property | Inverter derating | Solar sensor bias |
|---|---:|---:|
| First alert tick | 30 | 30 |
| Confirmation/detection tick | 32 | 30 |
| Representative source | Actuator/Inverter | Sensor |
| Resolved after quiet ticks | 114 | 116 |
| Reported status at end | Resolved | Resolved |

The sensor demo confirmed immediately because its anomaly reached critical. The
inverter demo used the three-warning confirmation window. Its representative
diagnosis was at tick 61, with classifier score 0.9834. The report retained 161
evidence records and cited observed unserved demand on the suspected inverter →
delivered-electricity edge.

The sensor demo highlighted solar sensor → communication → controller → inverter
→ delivered electricity. Those intermediate links are documented dependencies
compatible with observed downstream symptoms, not direct proof of fault transmission.
Reports explicitly distinguish this inference from measured residuals.

Full outputs are in `outputs/investigated-inverter` and `outputs/investigated-sensor`.
Compact measured reports are in [stage4-examples.json](stage4-examples.json).
These two demos verify the pipeline and are not an incident-detection accuracy
benchmark. Resolution means five quiet detector ticks, not proof that correction
caused recovery. No new ML performance numbers are claimed.

See [investigation contract](investigation.md) for lifecycle and graph semantics.
Stage 5 API/persistence and later frontend/sustainability work have not started.
