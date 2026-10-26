# Stage B: fault-versus-attack classification

All numbers in this document are from seeded synthetic simulator runs. They are not
evidence about real incidents, intent, or causal root cause.

## What was added

- A seeded corpus generator covers normal runs, every implemented fault mode in the
  five simulator fault families, all eight attacks (including multi-stage), three
  severities, varied starts and durations, and naive/moderate/stealthy attack levels.
- One causal incident window is formed from the first existing detector alert inside
  the event through up to 19 later ticks. A missed event has no prediction row and is
  counted as a detector miss. A no-fire normal run is not assigned an incident label.
- The model feature allowlist contains only security/message telemetry, measured
  component values, controller logs, residuals, and timing/cross-signal features.
  The extractor rejects keys containing attack/fault engine or ground-truth fields.
  Labels live in separate dataset columns and run manifests, never in the model input.
- Training and test sets are partitioned by whole run and unique seed. A second
  generalization run holds all stealthy attack runs out of training; normal and fault
  examples in that test are also held out by run.
- Nature and origin-layer Random Forests are separate from the existing source
  localizer. Low confidence/margin returns **Undetermined** or **Unknown**. Confidence
  scores are uncalibrated; no calibration claim is made.
- Attribution counts are computed from the telemetry window itself. Redundant sensor
  disagreement is marked ambiguous because it can result from either a fault or spoof.
  Text explicitly states that signals are indicators, not proof of intent.

The runnable command and saved artifacts are documented in the Stage B section of the
root README. The full per-group audit, including every fault mode, every attack and
stealth level, and a run-level search for global one-feature separators, is saved at
`outputs/stage4/telemetry_audit.json`.

## Step 0 telemetry realism audit

The baseline audit showed zero invalid authentication tags in normal traffic, invalid
tags on every communication-targeted message-tampering packet except when stealthy
tags were marked missing, and no normal solar disagreement after the prior 5% threshold.
Controller policy flags and firmware hashes were also deterministic within their
matching attack families. There was no single threshold separating the pooled attack
population from all fault and normal runs, but these family-level patterns would make
subtype attribution unrealistically certain.

The seeded simulator now adds 1% ordinary invalid-tag probability on an independent
random stream, allows tampering to retain valid tags (invalid-tag probability is 0.90,
0.70, and 0.25 for naive, moderate, and stealthy communication tampering), and has
redundant solar and SOC sensors use independent measurement noise with tighter
agreement thresholds. It also scales communication, controller, firmware, and actuator
attack strength as 1.0 / 0.65 / 0.35; replay repeats each 1 / 2 / 5 ticks. Solar spoofing
ramps at the stealthy level, and stealthy firmware hash reporting still delays its
integrity mismatch by five ticks. All randomness is seeded and isolated from the
weather/measurement/communication streams where applicable.

The final seeded audit found no global one-feature separator for attack versus the
combined fault/normal population. It intentionally retains some strong *family* signals
because those are real observable security checks, but the overlapping fault behavior
and injected telemetry imperfections prevent those signals from establishing intent.
Across 36 full normal runs, invalid authentication averaged 1.09%, missing tags 0.21%,
solar disagreement 3.66%, and SOC disagreement 3.29%; sequence anomalies, hash
mismatches, and policy inconsistencies were 0%. The same security checks also appeared
in faults: controller wrong-dispatch had a policy flag on 99.4% of active ticks,
firmware discharge-limit faults had hash mismatch on 100%, and sensor-bias faults had
solar disagreement on 100%. Therefore these checks can indicate a component/path but
cannot by themselves tell accident from attack.
Across the 396-run evaluation corpus, the existing detector fired on 93.0% of all
held-out runs in the ordinary split and 87.2% in the stealth-generalization split.
The normal-only detector fire rate was 77.8% and 66.7% respectively in these small
held-out normal samples, so the detector's false-alert behavior remains a clear weak
spot.

Selected attack-window audit means across severities 0.25, 0.6 and 1.0 (three seeded
runs per severity/level/target cell) show the intended strength gradient. Values below
are rates except where noted; the full per-type/per-level set is in the audit JSON.

| Observable signal | Naive | Moderate | Stealthy |
| --- | ---: | ---: | ---: |
| Replay sequence anomalies | 1.000 | 0.726 | 0.289 |
| Communication excess delay (ticks) | 2.667 | 2.000 | 1.333 |
| Controller command residual (normalized mean) | 0.359 | 0.231 | 0.185 |
| Actuator inverter output gap (normalized mean) | 0.305 | 0.200 | 0.110 |
| Multi-stage inverter output gap (normalized mean) | 0.186 | 0.106 | 0.038 |
| Solar spoof redundancy disagreement (solar-sensor target) | 1.000 | 1.000 | 0.554 |
| Message-tampering invalid-tag rate (communication target) | 0.891 | 0.583 | 0.249 |

These measurements show weaker but still observable cross-check, timing, sequence,
command, or inverter signals for the sampled stealthy cases. In the held-out classifier
evaluation some subtle attack families remain difficult and some attacks were missed;
their exact per-type miss rates are retained in the JSON report.

## Held-out classification results

The current artifact is trained with seed `72100`, three repeats per fault/attack
cell, 240 ticks per run, and the Stage 2 anomaly artifact. Test confusion matrices,
per-class precision/recall/F1, attack type/stealth/severity breakdowns, miss IDs, and
baseline comparison are in:

- `outputs/stage4/held_out_evaluation.json`
- `outputs/stage4/stealth_generalization_evaluation.json`

The ordinary split nature macro-F1 is **0.44** and origin-layer macro-F1 is **0.58**.
The nature model's held-out fault-versus-attack macro-F1 is **0.43**. It abstains on
about **38%** of nature results and **39%** of known-origin evaluations. Its normal
false-positive rate for the *Cyber attack* label is 0% on these nine normal test runs;
the upstream anomaly detector nevertheless fired on seven of the nine, causing a high
normal-run alert rate.

| Held-out measure | Ordinary run split | Stealthy-held-out split |
| --- | ---: | ---: |
| Complete test runs | 129 | 117 |
| Detector fired during event / normal observation | 120 (93.0%) | 102 (87.2%) |
| Nature macro-F1 | 0.439 | 0.416 |
| Fault-versus-attack macro-F1 | 0.435 | 0.412 |
| Origin-layer macro-F1 | 0.577 | 0.561 |
| Nature abstention rate | 38.0% | 47.9% |
| Origin abstention rate on fault/attack runs | 39.2% | 48.1% |
| Nature false-positive rate on normal runs (Cyber attack label) | 0 / 9 | 0 / 9 |
| Normal detector alert rate | 7 / 9 | 6 / 9 |
| Attack detector miss rate | 6.9% | 13.9% |
| Mean detector delay when an attack was detected | 3.63 ticks | 5.89 ticks |

The ordinary nature confusion matrix (rows are true; columns are predicted) is:

| True \ Predicted | Normal | Accidental fault | Cyber attack | Undetermined |
| --- | ---: | ---: | ---: | ---: |
| Normal | 3 | 1 | 0 | 5 |
| Accidental fault | 1 | 24 | 7 | 16 |
| Cyber attack | 0 | 4 | 40 | 28 |

On the separate fault-versus-attack subset, the corresponding matrix is
`[[24, 7, 16], [4, 40, 28]]` for true rows [Accidental fault, Cyber attack] and
predicted columns [Accidental fault, Cyber attack, Undetermined]. This makes the
misses and abstentions visible rather than folding them into a binary score.

Ordinary nature-class precision / recall / F1:

| Class | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| Normal | 0.750 | 0.333 | 0.462 |
| Accidental fault | 0.828 | 0.500 | 0.623 |
| Cyber attack | 0.851 | 0.556 | 0.672 |

Ordinary origin-layer precision / recall / F1:

| Origin | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| Sensor | 1.000 | 0.708 | 0.829 |
| Communication | 1.000 | 0.659 | 0.794 |
| Controller | 1.000 | 0.867 | 0.929 |
| Firmware-Config | 1.000 | 0.267 | 0.421 |
| Actuator-Inverter | 0.750 | 0.360 | 0.486 |

The held-out stealthy attack label rate is **44.4%** (32 of 72). By attack type in
that generalization split, rates were 0% for sensor spoof, 22% for actuator abuse,
22% for firmware tampering, 33% for message tampering, 11% for replay, 78% for
communication degradation, 89% for controller compromise, and 100% for multi-stage.
These are attack-label rates over all runs, so detector misses and abstentions count
as failures. See the linked JSON report for per-stealth and per-severity detector
coverage and the complete matrices.

The stealth-held-out generalization split yielded nature macro-F1 **0.42** and origin
macro-F1 **0.56**. The attack label rate on stealthy attacks was **44%**, so performance
does not generalize reliably to the held-out stealth level. The model is retained as an
experimental, abstaining layer, not a replacement for the detector or existing source
classifier.

On the same held-out fault runs and inference ticks, the new origin model's fault-only
macro-F1 is about **0.59**. The existing source classifier's macro-F1 on those same
runs is **0.82**, with accepted accuracy **0.98** at **97.8%** coverage (95.7% accuracy
including abstentions). That is a regression for fault-only localization;
the established source classifier remains unchanged and should continue to be preferred
for that task. The new layer adds the distinct, weaker nature judgment needed to explore
attack-versus-fault separation.

Uncalibrated scores are not probabilities. The model does not claim calibrated
confidence, and overall results are limited by synthetic data, a small number of
independent test runs, high normal detector alert rates, and observably overlapping
fault/attack behaviors. Results are intentionally reported without hiding weak stealth
performance.
