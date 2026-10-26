# Stage 3 source localization

## Model and uncertainty

The classifier learns six classes: Normal, Sensor, Communication, Controller,
Firmware/Configuration and Actuator/Inverter (`normal`, `sensor`, `communication`,
`controller`, `firmware`, `inverter`). Outputs are source hypotheses, not proven
root causes. The scikit-learn Random Forest has 200 trees, max depth 16, minimum
leaf size 4, balanced-subsample class weights, seed 42 and one worker. Scaling is
not required for its axis-aligned numeric splits.

Confidence comes from `predict_proba`, which averages tree-leaf class distributions
([official documentation](https://scikit-learn.org/1.6/modules/generated/sklearn.ensemble.RandomForestClassifier.html)).
It is an **uncalibrated classifier probability**, not a calibrated likelihood,
causal probability or reliability guarantee. The default policy, fixed before
validation/testing, requires top score >= 0.65 and top-two score margin >= 0.15.
Otherwise the output is `unknown`: "Unknown or insufficient evidence". Missing
state initialization also forces Unknown. Thresholds are configurable through
`ConfidencePolicy` or the training CLI.

Unknown is an abstention rather than a trained fault class. Its prediction-level
confidence is null, while the top candidate's actual score, ranked alternatives,
margin and explicit abstention reasons remain available. High-confidence mistakes
remain possible. Abstention does not reliably identify all unseen faults or regimes.

## Observable features

The localizer reuses Stage 2's eleven causal features without changing its schema
or saved anomaly model, and adds:

| Feature | Meaning |
|---|---|
| soc_level_residual_scaled | Measured SOC minus integrated SOC estimate, divided by 100 |
| soc_estimate_available | Whether the estimate started at a known reset |
| packet_soc_gap_scaled | Received packet SOC minus current measured SOC, divided by 100 |
| inverter_request_gap_scaled | Requested minus actual AC output, divided by PV rating |
| battery_power_scaled | Metered bus power divided by max(1 kW, charge/discharge limit) |

At tick zero the SOC estimate starts from configured initial SOC. Subsequent steps
integrate **previous metered battery power** over elapsed time using intended
capacity/efficiencies, clamping SOC to [0, 100]. This estimates the beginning-of-
interval state, matching the sensor sampling instant. A fresh extractor started
midstream cannot reconstruct missing history and forces Unknown. Keep the extractor
through correction; replace it after reset. Real use would require initialization
confidence, meter drift and capacity-aging models, which are absent here.

Only explicit allowlisted current/past observations and intended configuration are
read. Hidden physical `actual_solar_kw`, `battery_soc_pct`, `battery_energy_kwh`
and simulator `nominal_command_kw` are ignored. Run ID, seed, tick, severity,
fault mode, duration, source label, ground truth and future values are not feature
columns. Reference PV, bus/AC meters and configuration checks retain the observable
instrumentation assumptions described in [Stage 2](detection.md).

Exports include actual feature values and triggered residual checks. Added checks
report SOC-estimate disagreement > 5 percentage points and packet/local-PV
disagreement > 10% of rating. These are explicit hand-written observations, not
learned source decisions. Empty check lists can occur for subtle multivariate
predictions; there is no invented per-feature attribution. Competing sources can
explain the same residuals. Candidate-specific narratives and propagation remain
for Stage 4.

## Complete-run datasets

Partitions consist of independent complete runs, following the
[group isolation principle](https://scikit-learn.org/1.6/modules/cross_validation.html),
with no split between neighboring time-series rows.

| Partition | Normal runs | Fault runs | Seed range | Selected rows |
|---|---:|---:|---|---:|
| Training | 24 | 144 | 100000–100167 | 28,106 |
| Validation | 8 | 48 | 200000–200055 | 9,445 |
| Final test | 8 | 96 | 300000–300103 | 16,010 |

Every run has 360 one-minute ticks. Every partition covers all 16 modes at severities
0.25/0.6/1.0, with 3/1/2 independent repetitions for training/validation/test. Starts
vary between ticks 30–65; durations vary from 100–170 ticks. Fault start hours are
seeded choices of 6/10/16/20, including weakly observable night-time behavior.
Operating parameters and normal start hours vary as in Stage 2. All seed ranges
are disjoint from Stage 2.

Features are extracted before targets are assigned. Dedicated no-fault runs provide
Normal targets; active fault intervals provide injected-family targets. Pre-fault
and recovery intervals are excluded to avoid misleading Normal labels during
lingering effects. Even faults with no observable effect retain their injected
family target, exposing observability limits in the reported misses. Unknown is
never an injected ground-truth target.

Fit requires all known classes and checks duplicate run IDs/seeds. Evaluation
rejects training runs or reused training seeds. The CLI additionally enforces
disjoint training/validation/final-test partitions. Validation never retrains the
model or adjusts its policy.

## Evaluation and persistence

Reports include raw top-candidate accuracy, overall accuracy counting Unknown as
incorrect, coverage, accepted-prediction accuracy, Unknown rate, per-class
precision/recall/F1/support, macro F1, a 7×7 confusion matrix with an Unknown
prediction column, and per-mode/severity performance. The Unknown truth row is
zero because Unknown is abstention. Accepted accuracy must be read with coverage.

First-correct-localization delay averages only fault runs with at least one accepted
correct prediction; misses have null delay. It is not a stable-diagnosis metric.
Metrics are per correlated synthetic tick, without confidence intervals or field
generalization claims. Source predictions are **not gated by Stage 2 alerts**;
these are not end-to-end incident-localization metrics.

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m app.localization
```

`outputs/stage3` contains Joblib model/policy, training features with separate
metadata/target columns, manifests, validation and final-test reports. Only the
feature allowlist is fitted. The model stores schema, class vocabulary and
scikit-learn versions; incompatible or missing models fail explicitly. Load only
trusted Joblib artifacts. Generated artifacts are ignored by Git and reproducible.

```python
from app.localization import SourceLocalizer, LocalizationFeatureExtractor
from app.simulator import MicrogridSimulator

model = SourceLocalizer.load("outputs/stage3/source_classifier.joblib")
sim = MicrogridSimulator(seed=42)
extractor = LocalizationFeatureExtractor(sim.config)
prediction = model.predict([extractor.update(sim.step())])[0]
```

The simulator's `--source-model` exports per-tick `source_predictions.json`, alone
or alongside `--anomaly-model`. It does not merge predictions into telemetry or
scenario truth. Neither unavailable model is silently substituted. Stage 4 incident
propagation/explanations, API, persistence, frontend and sustainability comparisons
remain unimplemented.
