# Stage 2 validation — 2026-10-26

Environment: Windows, Python 3.12.14, NumPy 2.2.6, Pandas 2.2.3,
scikit-learn 1.6.1, SciPy 1.15.3, Joblib 1.4.2.

```text
.\.venv\Scripts\python.exe -m pytest -q
86 passed in 9.10s
```

The suite includes the 72 Stage 1 tests plus 14 detector tests for causal feature
extraction, batch/stream equivalence, normal-only fit, partition isolation,
ground-truth/oracle-field exclusion, thresholds, faulty/normal alerts, rule/ML
separation, missing models, persisted-model replay, schema compatibility, seeded
training, exact metric calculations, unobservable faults with null detection delay,
and scored simulator CLI integration. Dependency validation reported no broken
requirements.

## Measured held-out experiment

Training: 34,560 normal rows from 24 runs. Calibration: 11,520 normal rows from
8 separate runs. Testing: 11,520 normal ticks from 8 held-out normal runs and
15,360 active fault ticks from 96 other held-out runs. All partitions use disjoint
seeds. The full report, configuration manifests and results per mode/severity are
in [stage2-evaluation.json](stage2-evaluation.json).

Warning score threshold: 0.6024239527995616. Critical score threshold:
0.6659660185675378. Both were calculated from normal-only calibration scores.
Metrics below count either warning or critical as positive.

| Metric | Isolation Forest only | Residual rules only | Combined |
|---|---:|---:|---:|
| Active-fault-tick precision | 97.92% | 100.00% | 99.13% |
| Active-fault-tick recall | 29.68% | 68.39% | 71.89% |
| F1 | 0.4555 | 0.8123 | 0.8334 |
| Held-out normal-tick false-positive rate | 0.84% | 0.00% | 0.84% |
| Fault runs with at least one active-period alert | 69/96 | 81/96 | 91/96 |
| Mean first-alert delay, detected runs only | 648.70 s | 311.85 s | 123.96 s |

ML ROC AUC: 0.84037. ML average precision: 0.89163. Combined confusion counts:
11,043 true positives; 97 false positives; 11,423 true negatives; 4,317 false
negatives. These are synthetic anomaly-detection results, not source-localization
accuracy or evidence of real-world performance.

Weak combined active-tick coverage remains for SOC bias (~0.9%), one-step inverter
lag (~2.5%) and corrupted communication (~17.7%). Stronger modes include solar
bias (100%), firmware-setting deviations (100%), and controller wrong dispatch
(~99.9%). This does not imply every injected fault is observable, or that alerts
identify the source. See [methodology and limitations](detection.md).

## Saved model and scored demo

The fitted artifact is saved at `outputs/stage2/anomaly.joblib` (2,880,842 bytes).
`normal_training_features.csv`, `training_manifest.json` and `evaluation.json`
were also generated. Artifacts are reproducible and excluded from source control.

A 180-tick seed-42 demo loaded this saved artifact and injected solar sensor bias
at tick 30, planned duration 90 ticks, with correction at tick 90. It exported
telemetry, scenario truth, dependency topology, scores and alert events to
`outputs/scored-sensor`. This verifies the actual simulator-to-feature-to-model
path, separate from the evaluation dataset generator.

Stages 3–7 have not started. There are no fault-source predictions, live dashboard,
API or persisted incident records yet.
