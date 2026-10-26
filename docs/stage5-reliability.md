# Phase 2 Step 5 — Stage B reliability

Status: completed within the available telemetry. Origin acceptance improved; incident-nature accuracy did not improve. Incorrect and unclassified incidents remain. This is a simulation evaluation, not evidence of real-world cybersecurity accuracy.

## Diagnosis

The deployed Stage B artifact contains sigmoid-calibrated gradient-boosting estimators, not the Random Forest mentioned in some earlier descriptions. Its 32-feature version-2 schema and thresholds are nature 0.58, origin 0.52, top-two margin 0.08. Its original fitting windows include only 5 normal, 224 fault and 286 attack examples.

Two different conditions previously appeared as Unknown/Undetermined:

* Genuine nature uncertainty: seed 42 inverter shutdown and full-strength naive actuator abuse produce bit-identical observable telemetry for all 160 ticks. This was reproduced at seeds 42, 73 and 101. On seed 42, the model scores fault 0.525679 and attack 0.465898, with margin 0.059781. Both nature acceptance tests fail. Existing telemetry cannot establish intent in this pair.
* Coupled abstention: the origin model independently scores Actuator-Inverter 0.929996 with margin 0.905712, passing its thresholds, but the legacy policy forces Unknown whenever nature abstains. This discards useful physical-localization information.
* Missing evidence is separate: some message-tampering and stealth sensor incidents do not yield a qualified complete 20-tick Stage B window. They remain insufficient_evidence or pending, rather than being silently classified.

The original offline sampler can clip a window at a hidden simulated event end and uses the first global alert gate. Live inference uses the existing confirmed-incident lifecycle and a complete observed window. On 375 fresh held-out runs, legacy sampling produced 173 windows versus 170 live-ready windows; three legacy windows were short. Of 164 identical time windows, **zero** feature vectors differed. This is a sampling-protocol difference, not evidence of corrupted feature values. Historical evaluation and the new live-aligned evaluation must not be directly mixed.

Detailed raw scores, thresholds, reasons, complete telemetry-derived feature vectors, missing-window statuses and all 27 live cases are retained in [before diagnostics](../outputs/step5/live_diagnosis_expanded_before.json), [after diagnostics](../outputs/step5/live_diagnosis_after.json), and [window audit](../outputs/step5/window_protocol_audit.json).

## Minimal deployed change

The validated artifact revision opts into `origin_requires_determined_nature: false`. It contains the **same fitted nature and origin estimators** as the original. Origin may be accepted as a physical-layer hypothesis when nature is Undetermined, provided its own unchanged score and margin tests pass. An internally Normal nature prediction still suppresses origin. Unknown origins still produce no Stage B graph source. This does not establish malicious intent or compromise.

Legacy artifacts default to the old behavior. Explicit policy metadata is carried into the existing evidence graph so that it can represent an accepted physical origin without claiming an attack. Phase 1 source localization stays separate. Inference returns actual abstention reasons, margins and policy values for diagnostics.

Live and offline sampling share configuration scaling through `configured_features`; feature names, version, extraction mathematics, model weights, numeric thresholds, detection policy, physics and attack/fault behavior are unchanged. New offline sampling reuses the existing IncidentTracker and alert gate. Ground-truth event matching occurs only after observable windows are constructed, for evaluation labels. Future samples and hidden event-end boundaries do not enter those windows.

## Candidate fitting and selection

The existing generator created 1,620 independent 240-tick runs using seed 841600: 540 normal, 432 fault and 648 attack. Their seeds are disjoint from original Stage B fitting. Entire runs and seeds are separated into fitting, calibration, selection validation and final test sets. An additional 1,200 genuine simulated normal runs, seeds `2000000 + 17*i`, contribute only to candidate fitting/calibration, without balancing the test distribution. The regular RF fit has 443 qualified windows: 16 normal, 190 fault, 237 attack.

Candidates were the original artifact, an independent-origin policy copy, and two existing Random Forest configurations (raw and separately sigmoid-calibrated). RF uses the existing 320 trees, depth 16, minimum leaf 2, balanced class weights and one worker. No new architecture was introduced. All numeric abstention thresholds stay fixed.

Selection uses validation only: reject macro-F1 regressions greater than 0.01, accepted-accuracy regressions greater than 0.02, or normal false-attack rate increases greater than 0.01; maximize the sum of validation nature/origin F1 among eligible candidates. The decision and complete split manifests are written to `selection_before_test.json` before final test scoring. Final guards can reject promotion, not select a replacement from the test set.

Regular validation nature/origin macro-F1: original 0.539105/0.634432; independent origin 0.539105/0.707642. RF nature F1 was 0.513088 raw and 0.523667 calibrated, failing the nature guard (minimum 0.529105). **Neither retrained model was promoted.** The added training data therefore does not change the active estimators.

The dedicated stealth experiment uses the original dedicated stealth-exclusion estimator and its own alert policy. Stealthy cases are excluded from candidate fitting, calibration and selection validation. It is a separate evaluation, not a claim that the regular deployed estimator never saw stealth categories.

Two invalid experimental attempts are preserved and excluded: the first calibrated RF attempt accidentally reused calibration runs for validation and was rejected by the leakage assertion before fresh final test scoring (`attempt-1-validation/`); the first stealth comparison used the regular reference, which had seen stealth categories (`invalid-stealth-reference/`). The corrected comparison uses the dedicated reference and its own window cache. No final-test-driven parameter tuning was performed.

## Measured results

Faithfully recomputed historical protocol baseline: original 375-run held-out nature/origin macro-F1 **0.512843/0.601262**; original 459-run stealth baseline **0.465739/0.601644**. These are retained separately in `original_held_out_baseline.json` and `original_stealth_generalization_baseline.json`.

The following is the fair comparison on the **same fresh live-aligned 375-run final test**: 135 normal, 96 faults, 144 attacks. There are 170 complete Stage B windows (3 normal, 74 fault, 93 attack). Origin metrics use 167 complete windows with applicable known origin labels, from 240 event runs.

| Metric | Original policy | Independent origin |
| --- | ---: | ---: |
| Nature macro-F1 | 0.520622 | 0.520622 |
| Origin macro-F1 | 0.605733 | 0.694022 |
| Nature abstention, complete windows | 17.65% | 17.65% |
| Origin abstention, complete event windows | 18.56% | 1.20% |
| Nature accepted accuracy | 89.29% (140 accepted) | 89.29% (140 accepted) |
| Origin accepted accuracy | 97.06% (136 accepted) | 97.58% (165 accepted) |
| Nature coverage, complete windows | 82.35% | 82.35% |
| Origin coverage, complete event windows | 81.44% | 98.80% |
| Origin coverage, all event runs | 56.67% | 68.75% |
| Origin accuracy including misses/abstention, all event runs | 55.00% | 67.08% |
| Normal labelled Cyber attack | 0/135 | 0/135 |
| Stage B ready, all runs | 170/375 | 170/375 |
| Mean attack gate delay, complete attack windows | 6.75 ticks | 6.75 ticks |
| Mean classification delay, complete attack windows | 25.75 ticks | 25.75 ticks |

Macro-F1 retains the existing fixed label lists, including the abstention output class with zero true examples. Classification coverage/accepted accuracy are conditional on available windows; they are not detection recall or accuracy on all incidents. Unalerted normal runs are operational Normal states, not fabricated model predictions. Nature accuracy on complete windows including abstentions is 73.53%, unchanged; operational all-run nature accuracy including event misses and abstentions is 68.53%, unchanged. The 19-tick delay after firing is the existing complete 20-tick window requirement.

The dedicated **459-run stealth generalization test** has 135 normal, 108 fault, 216 attack runs, 235 complete windows, and 226 complete event-origin windows. Nature macro-F1 stays 0.518096; origin macro-F1 improves 0.596157 → 0.638786. Origin abstention falls 11.95% → 1.77%; accepted accuracy is 89.45% → 89.64%; origin coverage on complete windows 88.05% → 98.23%. Normal false-attack labels remain 0/135. Only 132/216 attack runs provide complete Stage B windows. Mean gate/classification delays are 11/30 ticks on those windows, unchanged.

The unchanged Phase 1 detector has substantial false alarms. On the regular 375-run audit, 95/135 normal runs have any alert, 37/135 have a confirmed incident, and 3/135 provide a complete Stage B window. For fault runs the corresponding counts are 93/96, 83/96, 74/96; for attack runs 132/144, 115/144, 93/144. Alerts during the injected event occur in 91/96 fault and 125/144 attack runs. These quantities are distinct from Stage B false Cyber attack labels. The report's legacy `detector_coverage` and `missed_attack_rate` field names refer to Stage B-ready sampling, not raw Phase 1 recall.

Full confusion matrices, per-class precision/recall/F1, conditional metrics, attack-type, severity and stealth breakdowns, delay summaries and individual row outcomes are in:

* [Regular comparison](../outputs/step5/candidates/regular/comparison.json)
* [Regular before details](../outputs/step5/candidates/regular/baseline_held_out_reliability.json)
* [Regular after details](../outputs/step5/candidates/regular/held_out_evaluation_reliability.json)
* [Stealth comparison](../outputs/step5/candidates/stealth_generalization/comparison.json)
* [Stealth after details](../outputs/step5/candidates/stealth_generalization/held_out_evaluation_reliability.json)
* [Selection, splits and candidate validation](../outputs/step5/candidates/regular/selection_before_test.json)
* [Calibration-set permutation importance](../outputs/step5/candidates/regular/validation_feature_importance.json)

Scores are model scores, not guaranteed or calibrated real-world accuracy. The historical estimators have sigmoid calibration metadata, but that alone does not establish reliability on new incidents.

## Actual live and browser outcomes

The complete 27-case diagnostic matrix uses nine scenarios at seeds 42, 73 and 101, with 160 ticks per run. It includes unfavorable results, not just chosen successes.

| Scenario | Actual result |
| --- | --- |
| Seed 42 sensor bias, severity 0.8 | Accidental fault / Sensor |
| Seed 42 naive replay, severity 0.8 | Cyber attack / Communication |
| Seed 42 inverter shutdown | Undetermined / Actuator-Inverter |
| Seed 42 naive actuator abuse, severity 1 | Undetermined / Actuator-Inverter; telemetry matches shutdown |
| Seed 42 message tampering | Insufficient complete evidence windows; no invented classification |
| Seed 42 naive sensor spoof, severity 0.8 | **Incorrect nature: Accidental fault / Sensor** |
| Seed 101 stealthy sensor spoof, severity 0.25 | **Incorrect nature: Accidental fault / Sensor** |
| Seeds 73 and 101 naive actuator abuse | **Incorrect nature: Accidental fault / Actuator-Inverter** |
| Normal defaults, seeds 42/73/101, 160 ticks | No incidents |

Browser verification used the actual running API with the candidate hash. Sensor-fault classification was Accidental fault / Sensor, nature score 0.593053, origin 0.918043, inference tick 31. Replay was Cyber attack / Communication, scores 0.906068/0.789127, inference tick 32. Existing graph node selection exposed recorded Solar Sensor/Communication evidence. The existing simulated corrective-action button returned “Simulated correction applied.” Start/pause/reset, injection controls, history, navigation and sustainability were exercised without React changes.

A separate normal held-out configuration, seed 846434, was replayed through the public API to tick 182. It has a real false-positive incident and returns **Undetermined / Unknown** at tick 181 (nature top score 0.449435; raw origin top 0.457). The browser displays both abstentions and actual observations. This is a normal false alarm, not a successfully detected attack. No Stage B origin is fabricated. Its config, evidence and result are retained in `browser_uncertainty.json`. A fresh default seed-42 normal run then produced zero incidents over 160 ticks; energy-balance residual was approximately 3.55e-15 kWh (`browser_normal.json`). The simulator was left paused.

Browser records/screenshots: `browser_fault.json`, `browser_attack.json`, `browser_uncertainty.json`, `browser_normal.json`, `browser-reliability.png`, `browser-uncertainty.png`, under `outputs/step5/`.

## Activation and reproduction

Original anomaly, localization and Stage B binaries/reports are preserved byte-for-byte. Original Stage B copies are under `outputs/step5/original/`. The candidate and reports are separate, under `outputs/step5/candidates/`. Promotion manifest: `outputs/step5/promoted.json`; candidate SHA256 `293e4b9eb92f983a0e8b7a645968d60ec2da4dba9f75060547bb97843232139d`.

The API currently runs with the evaluated revision through the opt-in launcher. Future plain uvicorn startup uses the original configured artifact; use this launcher to activate the evaluated revision without overwriting it:

```powershell
.\scripts\run_reliable_api.ps1
```

The launcher verifies promotion guards and artifact SHA, sets only the current process's security-model/report environment overrides, binds localhost:8000 with one worker, and restores prior environment values on exit. Root frontend startup remains `npm run dev -- --port 5173`. No package installation is required in the existing environment.

Reproduction from the repository root, after preserving the original Stage B files in `outputs/step5/original/`:

```powershell
$env:PYTHONPATH = 'backend'
.venv\Scripts\python.exe scripts/diagnose_stage_b.py --filename live_diagnosis_expanded_before.json
.venv\Scripts\python.exe scripts/diagnose_stage_b.py --original-baseline
.venv\Scripts\python.exe scripts/evaluate_stage_b_reliability.py --seed 841600 --repeats 9 --ticks 240 --extra-normal-runs 1200
.venv\Scripts\python.exe scripts/summarize_stage_b_reliability.py
.venv\Scripts\python.exe scripts/diagnose_stage_b.py --model outputs/step5/candidates/regular/selected.joblib --results outputs/step5/candidates/regular --filename live_diagnosis_after.json
.venv\Scripts\python.exe scripts/diagnose_stage_b.py --audit-windows
.venv\Scripts\python.exe -m pytest backend/tests -q
npm test
npm run typecheck
npm run build
```

Existing caches contain genuinely generated observations, not dummy artifacts. A different configuration should use a new output directory and unchanged originals. Diagnostic baseline commands use default original settings, independently of the running API's launcher environment.

## Source changes and regression verification

Modified this step: `backend/app/security_analysis/{model,features,dataset,evaluation}.py`, `backend/app/api/runtime.py`, `backend/app/propagation/investigation.py`.

Created this step: `backend/tests/test_stage_b_reliability.py`, `scripts/diagnose_stage_b.py`, `scripts/evaluate_stage_b_reliability.py`, `scripts/summarize_stage_b_reliability.py`, `scripts/run_reliable_api.ps1`, and this document. Generated data, artifacts, reports, snapshots and browser evidence reside under `outputs/step5/` (ignored generated outputs).

Full backend: **242 passed, 0 failed**, four non-failing existing warnings. New reliability module contributes 12 parametrized tests. Full frontend: **66 passed, 0 failed**. TypeScript and production build pass. No lint command is configured. Existing tests were not edited this step. Frontend `src/`, unused `frontend/`, package files, styling and UI customizations retain their pre-step bytes; earlier uncommitted Step 1–4 changes are preserved. No dependencies were installed or upgraded, no database schema changed, no commit or push was made.

Remaining limits: fault-versus-attack confusion, sparse qualified normal fitting windows, weak stealth detection, incomplete windows, detector false alarms, synthetic distribution bias, and limited normal sample size. More reliable intent discrimination for identical actuator telemetry would require independently authenticated applied-command/configuration audit or comparable independent device observations. No such nonexistent telemetry was invented. This step does not claim to solve that information deficit.

Phase 2 Step 6, ShadowTwin, counterfactual features, Autonomous Investigation Agent and Proof Mode were not implemented.
