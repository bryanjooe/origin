# Stage B improvement pass

All results below are from seeded synthetic simulator runs. They do not establish
real-world attack intent or causal root cause. The full per-attack / stealth and
per-fault telemetry summary is in [stage5-telemetry-audit.md](stage5-telemetry-audit.md).

## 1. Alert diagnosis and threshold selection

**Before:** the previous 396-run corpus showed alerts in 7/9 normal runs in the
ordinary holdout and 6/9 in the stealth holdout. The detector compared each tick's
Isolation Forest score with a warning limit set at a point-level normal 99th
percentile, then promoted any one tick's warning or residual rule to a run alert.

**Validation diagnosis:** in the expanded run-level validation partitions, 59/81
(72.8%) and 62/81 (76.5%) normal runs had at least one legacy alert. All those runs
had an ML score alert; none had a residual-rule alert. Median first alert was tick 37
and tick 22 respectively. Normal-run maximum scores had long upper tails (95th
percentiles 0.710 and 0.689), showing why a point-level threshold creates frequent
run alerts over a 240-tick run. The evidence points to per-tick score calibration plus
many opportunities to cross it, rather than the separate residual rules. Normal
cloud/load variation is included in those seeded runs; this analysis does not claim
one specific physical cause for every high score.

**After:** for each protocol, the score cutoff and warm-up were selected using its
training-derived validation runs only. The chosen policy waits 12 ticks, then alerts
on a score at/above the validation run-maximum threshold; a persistence requirement
was tested but did not improve validation event coverage under the 5% false-alert
constraint. The selected thresholds were 0.710 (ordinary) and 0.689
(stealth-generalization). Validation normal alerts were 4/81 (4.9%) in each protocol;
event coverage was 71.7% and 76.6%. On held-out normal runs the alert rate was 0/135
(ordinary) and 6/135 (4.4%) (stealth-generalization). The coverage cost is material:
attack misses rose to 33.3% and 42.6%, and mean alert delay rose to 8.71 and 11.95
ticks. This is an explicit precision/coverage tradeoff, not an unqualified detector
improvement.

## 2. Dataset expansion and split protocol

**Before:** 396 independent runs: 36 normal, 144 faults, and 216 attacks.

**After:** 1,620 independent seeded runs: 540 normal, 432 faults, and 648 attacks
(4.1x total). This includes all fault modes, all eight attack types including
multi-stage, three severity levels, three stealth levels, varied event start ticks
and durations. Nature-class counts are within a 1.5x range. The ordinary and
stealthy-held-out protocols split on complete runs and unique seeds; the stealth
protocol excludes stealthy attack runs from training. Feature windows end at
inference time and do not include future telemetry.

## 3. Observable feature pass

**Before:** 25 observable incident-window features; no feature-importance report.

**After:** added onset step ratio, longest persistent-signal run, signed primary vs
redundant sensor gaps, invalid-tag rate relative to a pre-event baseline, controller
command alignment with observed power deficit, and multi-signal consistency. The
pre-event comparison and incident window use only telemetry available by inference
time. The allowlist still rejects hidden engine and label fields.

Permutation importance on held-out runs is explanatory only and did not affect model
choice. In the ordinary split, top overall features were unmet demand (0.154), solar
redundancy gap (0.142), persistent-signal run (0.130), sequence anomalies (0.072),
message age (0.052), and maximum inverter gap (0.045). For stealthy attack/fault
distinction, the top ordinary-holdout signals were onset sharpness (0.219),
persistent-signal run (0.130), sequence anomalies (0.064), solar redundancy gap
(0.055), and message age (0.043). On the separately stealthy-held-out test, top
signals were config-hash mismatch (0.262), multi-signal consistency (0.252), message
age (0.197), sequence anomalies (0.040), and packet drops (0.035). Importances vary
by split and several features had near-zero or negative permutation scores; these
signals help some synthetic stealthy cases but do not solve generalization.

The Stage A seeded telemetry imperfections were retained. Across 540 normal runs,
invalid tags averaged 1.04%, missing tags 0.14%, solar sensor disagreement 3.77%, and
battery sensor disagreement 3.30%. The expanded audit found no single feature that
perfectly separates all attacks from the combined fault/normal runs. Some narrow
family-level signals remain strong, such as sequence anomalies in naive replay, but
those are indicators rather than proof of intent.

## 4. Model comparison and calibration

**Before:** one Random Forest with balanced-subsample weights; confidence scores were
uncalibrated.

**After:** class-weighted Random Forest and class-weighted histogram Gradient Boosting
were compared on validation nature macro-F1. Gradient Boosting was selected for the
ordinary split (0.518 vs 0.503); Random Forest was selected for stealth-generalization
(0.519 vs 0.518). Selection did not use test scores. The chosen models use sigmoid
probability calibration fit on run-disjoint validation windows. Held-out Brier score
and 10-bin expected calibration error were 0.269 / 0.057 (ordinary) and 0.316 / 0.070
(stealth-held-out); lower is better. Calibration is imperfect, especially on the
unseen stealth level.

## 5. Held-out results: before and after

The prior baseline used a smaller corpus, so the table compares the same split
*protocols* and metric definitions, not identical run IDs. Old coverage counted every
legacy alert including false alerts on normal runs; this explains why new coverage is
lower after controlling normal alerts.

| Metric | Prior ordinary | New ordinary | Prior stealth-held-out | New stealth-held-out |
| --- | ---: | ---: | ---: | ---: |
| Nature macro-F1 | 0.439 | 0.513 | 0.416 | 0.466 |
| Fault-vs-attack macro-F1 | 0.435 | 0.421 | 0.412 | 0.393 |
| Origin-layer macro-F1 | 0.577 | 0.601 | 0.561 | 0.599 |
| Detector run coverage | 93.0% | 44.8% | 87.2% | 46.2% |
| Normal detector alert rate | 7/9 (77.8%) | 0/135 (0%) | 6/9 (66.7%) | 6/135 (4.4%) |
| Attack detector miss rate | 6.9% | 33.3% | 13.9% | 42.6% |
| Mean alert delay on detected attacks | 3.63 ticks | 8.71 ticks | 5.89 ticks | 11.95 ticks |
| Nature abstention rate | 38.0% | 6.9% | 47.9% | 3.7% |

Nature macro-F1 improved on both protocols, but binary fault-versus-attack F1,
detector coverage, and attack detection delay worsened. The new nature output maps a
run with no detector alert to **Normal**; missed faults and attacks therefore count as
false negatives, not as fabricated incident predictions. On alerted runs, the model
can still return **Undetermined**. The normal false attack-label rate was 0/135 on
both held-out sets.

For stealthy attacks, the overall attack-label rate was 50.0% (ordinary split) and
49.1% (stealth held out), including missed detections. The stealth-generalization
binary F1 was 0.393. Fault-only origin localization remains weaker than the existing
source classifier: new origin macro-F1 was 0.636 vs 0.833 for the unchanged source
model on the same held-out fault runs. The existing source classifier and its API path
were not modified.

The remaining nature-classification weakness is expected from the available signals:
stealthy attacks can preserve valid tags, create small changes that resemble sensor,
communication, or controller faults, and do not always leave a unique intent signal.
The simulator does not expose independently verifiable command authorization,
attacker identity, or a trusted provenance chain. Without those observables, a
fault-versus-attack verdict should remain cautious; the results are not evidence of
intent.

## 6. Added checks and artifacts

Six seeded tests were added for alert gating/calibration, balanced expanded
generation, causal baseline/cross-signal features, both candidate models and
run-disjoint calibration, run-level calibration partitions, and the no-alert Normal
evaluation rule. Existing tests were retained. The output artifacts are generated locally under ignored `outputs/stage5/`:
the feature CSV, metadata/configuration, full telemetry audit, and both evaluation
JSON files. They are reproducible with:

```sh
PYTHONPATH=backend python -m app.security_analysis --repeats 9 --seed 72100 --output-dir outputs/stage5
```

