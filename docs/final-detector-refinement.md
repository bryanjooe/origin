# Final detector refinement — optimization stopped

Neither of the two final-attempt candidates passed every validation requirement.
No model, threshold, production configuration or application feature was changed.
The reserved final corpus remains ungenerated and uninspected.

## Findings

The previous 180/192 to 175/192 coverage change was six lost runs and one gained
replay run. Every lost run had isolated ML warnings, zero critical alerts and zero
physical residual alerts. All four new signal domains met minimum availability
during those events. The three-consecutive-warning policy removed their only
detection; missing data and changed thresholds were not the primary cause.

Stage B changed windows/predictions in 37 runs. It went from 98 correct out of 120
accepted predictions to 105 out of 134: eight newly correct and eight newly wrong
outputs, plus one correct and one wrong prior output becoming unaccepted.
Empirical security indicators appended to `residual_checks` could open the
existing calibrated gate on different, sometimes benign or ambiguous evidence.

The final policies use immediate, rate-limited weak-warning onsets and separately
labeled security observations. One requires three findings in three ticks; the
other requires two in three, including a current actual finding. Original scores,
physical residuals, critical alerts, thresholds and Stage B gate remain unchanged.
This restores all prior event detections, preserves the availability of Stage B
windows on every previously gated event, and preserves all nature/origin prediction
labels, including accepted accuracy of 81.67%. One window changes timing:
run00149 infers at tick109 instead of119, with the same Accidental fault label.

## Validation decision

| Metric | Original | Candidate A | Candidate B |
|---|---:|---:|---:|
| Precision | 95.51% | 96.15% | 95.99% |
| Active-tick recall | 71.57% | 80.36% | 80.63% |
| F1 | 81.82% | 87.55% | 87.65% |
| False-positive rate | 1.69% | 1.62% | 1.69% |
| Event runs detected | 180/192 | 181/192 | 181/192 |
| Detected-only delay, simulated seconds | 180.33 | 149.17 | 144.53 |

Both fail the unchanged **1.50% absolute false-positive ceiling**. Candidate A
exceeds the permitted 432 false ticks by 34; candidate B by 56. Every other
original guard passes. Additional checks also preserve each baseline detected
event and each baseline Stage B event window, preventing aggregate metrics from
hiding lost incidents. Acceptance limits were not weakened to accept a near miss.

All results are validation results on the same 312 complete runs as the prior
study, not final-test or deployed metrics. Security-signal improvements for replay,
sensor spoofing and message tampering remain visible; communication-degradation
delay returns from 627.27 to 152.73 seconds, but its tick recall remains below the
original. The full report lists every missed run and before/after evidence-window
features under `outputs/final-detector-refinement/REPORT.md`.

## Reproduction and saved evidence

Using the existing environment and trusted prior artifacts:

```powershell
$env:PYTHONPATH = 'backend'
$env:OMP_NUM_THREADS = '1'
.venv/Scripts/python.exe scripts/final_detector_refinement.py diagnose
.venv/Scripts/python.exe scripts/final_detector_refinement.py validate
.venv/Scripts/python.exe scripts/final_detector_refinement.py final
.venv/Scripts/python.exe scripts/final_detector_refinement.py report
```

These phases have already run. Diagnosis/selection refuse to overwrite their
records. `final` rejects without opening held-out data when validation selects
nothing. `report` only derives reports from saved measurements. Use existing
results in this checkout; independent reproduction belongs in a fresh directory
with the same model hashes. Do not reopen the final corpus or add candidates.

No retraining occurred: both policies reuse the frozen Normal-calibrated
`envelope999.joblib`. Evaluation labels are used only after inference. The
experimental interface receives observable detector outputs and signal samples;
it has no simulator, schedule, target or true-source input. Previous reports and
artifacts remain intact. No rejected candidate is wired into the runtime.

Only four new source/documentation files were added. Existing frontend, physics,
injection, incident API, ShadowTwin and agent code were not edited. Rollback is
unnecessary. No commits or pushes were made. This is the end of planned automatic
AI optimization; preserving reliability takes priority over aggregate F1 gains.
