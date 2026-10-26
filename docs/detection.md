# Stage 2 anomaly detection

## Model and score

The detector is scikit-learn's Isolation Forest with 200 trees, up to 512 sampled
rows per tree, `contamination="auto"`, `random_state=42` and one worker for repeatable
training. Features are physically normalized, then transformed by a StandardScaler
fit only on training data. Axis-aligned tree splitting does not require scaling;
the scaler provides a consistent persisted preprocessing pipeline.

The score is `-pipeline.score_samples(X)`: larger means less similar to normal
training observations. It is not a probability, source confidence, or severity
estimate. The model's default contamination decision threshold is not used.
Warning and critical limits are the 99th and 99.9th percentiles of scores from a
separate normal-only calibration partition, with a minimum gap of 0.01. Neither
threshold uses fault examples or test results. Quantiles are configurable at
training time; `Thresholds` allows explicit inference overrides. A critical label
describes statistical deviation, not proven physical danger.

## Information boundary and features

`FeatureExtractor` is stateful per run, maintains an eight-observation trailing
window and accepts consecutive time-ordered rows. Online and batch extraction use
identical code. The first SOC/change residual has no prior observation and is zero.
No future samples or centered windows are used. Create a fresh extractor on reset
and when switching runs. Do not use a different window with an existing model.

Only named telemetry fields and the intended healthy `GridConfig` are read. The
feature vector has an explicit allowlist:

| Feature | Inputs and meaning |
|---|---|
| solar_residual_z | Measured minus expected PV, divided by max(0.1 kW, 1.5% of expected PV) |
| soc_step_residual_z | Successive measured SOC change minus expected change from previous battery bus power, divided by 0.1 percentage points |
| inverter_residual_scaled | Expected AC using measured PV, battery power, request and healthy efficiency minus actual AC, divided by PV rating |
| command_residual_scaled | Issued command minus independently reconstructed intended dispatch, divided by max(1 kW, charge/discharge limit) |
| message_age_excess_ticks | Received packet age beyond configured baseline delay; missing startup packets use elapsed ticks beyond baseline delay |
| packet_solar_gap_scaled | Received packet PV minus current local measured PV, divided by PV rating |
| configuration_deviation | Maximum normalized deviation of applied reserve/discharge limit from intended settings or integrity failure |
| unmet_fraction | Unserved fraction of current demand; genuine normal shortages are included during normal training |
| solar_change_scaled | Current minus previous measured PV, divided by PV rating |
| solar_residual_mean | Trailing mean of standardized PV residual |
| solar_residual_std | Trailing population standard deviation of standardized PV residual |

`actual_solar_kw`, physical `battery_soc_pct`, `nominal_command_kw`, fault family,
mode, severity, label, future fault schedule, and ground-truth source are not read
by the feature extractor. Dispatch consistency is reconstructed from packet inputs
and intended settings instead of trusting the simulator's nominal-command field.

These are software-simulation observables. Expected PV is an idealized irradiance
reference, battery bus power and actual AC output are assumed available metering,
and configuration integrity is a synthetic status check. Those assumptions need
independent instrumentation and validation before physical deployment. No field
data or real-world generalization is claimed.

## Explicit residual rules

Isolation Forest cannot reliably detect deviations along features that were
constant during normal training. Alongside ML the detector reports these rules:

| Rule | Warning when |
|---|---|
| PV measurement residual | Absolute standardized residual > 5 |
| SOC step residual | Absolute standardized residual > 5 |
| Inverter output residual | Absolute expected/actual difference > 0.1 kW + 4% of PV rating |
| Controller policy residual | Absolute command difference > 0.1 kW |
| Stale telemetry | Age > configured delay + 3 ticks |
| Configuration integrity | Normalized configuration deviation > 0.01 |

Every triggered rule reports its actual value, threshold, units and
`method="residual_rule"`. Rules are hand-written checks, not machine learning.
`ml_status` derives only from the Isolation Forest score; `rule_status` derives
only from these checks. `combined_status` is the higher ML severity, or warning
when a rule alone fires. ML-only alerts can have an empty `affected_variables`
list: the multivariate score does not provide defensible per-feature attribution.
There is no invented feature importance, causal explanation or predicted source.

## Dataset and held-out evaluation

The default deterministic experiment uses:

- Training: 24 complete normal runs × 1,440 ticks, seeds 1000–1023.
- Calibration: 8 complete normal runs × 1,440 ticks, seeds 10000–10007.
- Normal test: 8 complete runs × 1,440 ticks, seeds 20000–20007.
- Fault test: 96 complete runs × 360 ticks, seeds 30000–30095. All 16 modes,
  severities 0.25/0.6/1.0, two independent runs per combination. Each has a
  160-tick fault starting at a seed-derived tick between 40 and 69; starts are
  at simulated hour 10 or 16.

Configurations vary deterministically: PV 10–14 kW, base demand 6–8 kW, battery
20–30 kWh, initial SOC 35–85%, normal starts at 0/6/10/16/20 hours, baseline delay
0 or 1 tick, and normal packet-loss probability 0 or 0.005. Other settings use
`GridConfig` defaults. These bounds define the demonstrated operating envelope.

All random seeds and run IDs are disjoint. Fit rejects scenarios marked faulty.
Evaluation rejects any training/calibration run or reused seed. Neighboring rows
from the same scenario are never split between partitions. Separate measurement
and weather RNG streams retain reproducibility.

Inference happens before labels are consulted. Metrics count all active injected
fault ticks as positives, even when the injected behavior has no observable effect.
Only dedicated no-fault runs supply negatives; pre-fault and post-fault ticks from
fault runs are excluded because effects can persist after fault expiry.
The report provides confusion counts, precision/recall/F1, normal-tick false-positive
rate, ML ROC AUC and average precision, per-mode/severity active-tick recall, fault
run detection count, and first-alert delay from injection onset.

Detection delay is averaged over detected runs only; missed runs explicitly have
null delay. False-positive rate is per tick, not a guarantee about alert frequency
per run. Alerts are not debounced into incidents. Temporal correlation and this
small synthetic scenario family limit the interpretation of all reported metrics.
There are no confidence intervals or claims of independent row observations.

## Persistence, use and limits

```python
from app.detection import AnomalyDetector, FeatureExtractor
from app.simulator import MicrogridSimulator

model = AnomalyDetector.load("outputs/stage2/anomaly.joblib")
sim = MicrogridSimulator(seed=42)
extractor = FeatureExtractor(sim.config)
result = model.predict([extractor.update(sim.step())])[0]
```

The artifact contains preprocessing, fitted trees, calibrated thresholds, feature
schema version, scikit-learn version and training/calibration manifests. Loading
rejects mismatched schema or scikit-learn versions. Load only trusted Joblib files;
they use pickle serialization. Missing/untrained models raise explicit errors.

The full measured experiment is checked in as `docs/stage2-evaluation.json`;
the artifact and feature CSV are generated locally under `outputs/stage2`. Rerun
the command in README to reproduce them. Exported training features include run
IDs/ticks as metadata columns, but fit selects only the feature allowlist.

Observed limits include weak sustained SOC-bias detection (a step residual catches
the transition rather than a constant offset), small inverter lags near normal
variation, and corrupted packets that do not produce a large physical effect.
Normal-baseline IF scores also saturate on some novel signals rather than scaling
with fault severity. The held-out results were measured once with the specified
settings; thresholds were not optimized on that test set. Future tuning needs a
development partition and a fresh final test set.

Stage 3 now adds [source classification and unknown-source handling](localization.md).
Incident explanations, API/live UI, SQLite persistence, and sustainability
counterfactuals remain for later stages. Stage 2 anomaly performance above is
unchanged by Stage 3's additional features and classifier.
