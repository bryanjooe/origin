# Stage 3 validation — 2026-10-26

Environment: Windows, Python 3.12.14, scikit-learn 1.6.1 and existing pinned Stage 2
dependencies. No additional runtime dependencies were needed.

```text
.\.venv\Scripts\python.exe -m pytest -q
101 passed in 16.81s
```

The 15 new tests cover scenario isolation, feature/target separation, hidden-label
and physical-oracle exclusion, no future lookahead, streaming equivalence, SOC
estimate initialization/recovery, Normal and all five fault-family predictions,
confidence/margin abstention, missing-state Unknown, actual residual evidence,
model persistence/compatibility, unavailable models, policy validation, incomplete
training classes, metrics including Unknown, CLI exports and repeatable training.
All 86 previous tests still pass.

## Measured held-out experiment

Training used 28,106 selected rows from 168 independently seeded runs. Validation
used 9,445 rows from 56 separate runs. Final testing used 16,010 rows from 104
further runs: 2,880 normal ticks and 13,130 active fault ticks. Policy thresholds
were fixed beforehand: confidence 0.65, top-two margin 0.15.

| Final test metric | Result |
|---|---:|
| Raw top-candidate accuracy, without abstention | 87.80% |
| Overall accuracy, Unknown counted as incorrect | 81.57% |
| Coverage, non-Unknown predictions | 89.08% |
| Accuracy among accepted predictions | 91.56% |
| Unknown rate | 10.92% |
| Macro F1 over six known classes | 0.8862 |
| Fault runs with at least one correct accepted localization | 91/96 |
| Mean first-correct delay among those 91 runs | 47.47 s |

Validation accuracy including Unknown was 82.64%, coverage 89.83%, and accepted
accuracy 92.00%. These scores were not used to tune the frozen model/policy.

| True source | Precision | Recall | F1 | Test ticks |
|---|---:|---:|---:|---:|
| Normal | 62.96% | 70.35% | 0.6645 | 2,880 |
| Sensor | 100.00% | 85.05% | 0.9192 | 4,107 |
| Communication | 99.63% | 89.83% | 0.9448 | 3,325 |
| Controller | 100.00% | 99.76% | 0.9988 | 835 |
| Firmware/Configuration | 100.00% | 100.00% | 1.0000 | 1,568 |
| Actuator/Inverter | 100.00% | 65.31% | 0.7902 | 3,295 |

These are synthetic classification metrics, not causal proof or deployment
validation. Firmware integrity is particularly distinctive in this simulator.
Normal precision is limited by weakly observable active faults predicted Normal.
Dedicated normal test ticks comprised 2,026 Normal, 848 Unknown and 6 incorrect
Communication predictions. Inverter lag and stuck sensors remain challenging when
effects resemble healthy behavior. Abstention does not catch every unfamiliar fault.

The full confusion matrix, per-mode/severity results, miss delays and scenario
manifests are in [stage3-evaluation.json](stage3-evaluation.json). Exact definitions
and assumptions are in [localization methodology](localization.md).

## Saved-model demo

The saved `outputs/stage3/source_classifier.joblib` is 7,663,611 bytes. Training
features, manifests and validation/final reports were also saved locally; these
artifacts are reproducible rather than committed.

A 180-tick seed-42 demo loaded both saved models, injected inverter derating 0.8
at tick 30, with planned duration 120 ticks and correction at tick 110. Files are
in `outputs/localized-inverter`.

- Before injection (ticks 0–29): 28 Normal, 1 Unknown, 1 incorrect Sensor prediction.
- During fault (ticks 30–109): all 80 predictions were Actuator/Inverter.
- After correction (ticks 110–179): 57 Normal and 13 Unknown predictions.

Tick 40 inverter score was 0.98109; tick 120 Normal score was 0.70848. These are
actual uncalibrated classifier scores. Telemetry, anomaly scores, source hypotheses
and hidden truth were exported separately. The startup error and abstentions are
retained in the record.

Stage 4 and later work have not started: no incident-specific propagation inference,
causal narrative, API, dashboard or database is implemented yet.
