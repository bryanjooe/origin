# Targeted upstream security-signal study

No candidate qualified for activation. Production model artifacts, loading
configuration, APIs, UI, physics and agent behavior remain unchanged. This study
does show useful validation signal: the rejected persistent envelope increased
combined tick recall from 71.57% to 79.29% and F1 from 81.82% to 88.16%, with
precision increasing from 95.51% to 99.27% and false-positive rate decreasing
from 1.69% to 0.30%. These are **validation results**, not final-test or deployed
accuracy. Raw Isolation Forest scores and ML labels were never changed.

The refinement failed event-coverage and downstream Stage B safeguards. Its
accepted nature accuracy fell from 81.67% to 78.36%; normal false attack labels
rose from 0/120 to 2/120. Event coverage fell from 180/192 to 175/192. No final
holdout was opened to justify promoting a candidate that failed validation.

## Evaluated signals

All signals come from existing tick telemetry:

- Authentication validity, aggregated over distinct observed packet identities.
  A stale invalid packet is counted once. Missing/unknown tags are unavailable.
- Existing duplicate/out-of-order sequence flags from sender/receiver logs.
- Independent primary/redundant solar disagreement divided by rated capacity.
- Independent primary/redundant SOC disagreement divided by 100.

Extraction uses at most eight current/past ticks and at least four valid
observations per domain. Explicit counts prevent missing values from becoming
healthy zeros or invented anomalies. The normal-only auxiliary IF skips incomplete
windows. There is no independent redundant demand measurement here, so one was
not invented for demand-sensor spoofing. Hidden labels and schedules are never
read by extraction or fusion.

The old command and configuration features are constant during Normal fitting
and have no Isolation Forest splits. Existing residual rules remain unchanged.
The new sequence rate is also Normal-constant and is excluded from the learned
sidecar. Its empirical normal bound is explicitly a rule, not learned importance.

## Bounded experiments and decision

Three initial candidates were predeclared: envelopes at .995/.999 Normal
calibration quantiles and one 100-tree Normal-only IF at .999. They failed
validation. Their results and original selection remain preserved.

One explicit amendment tested a fixed three-tick persistence refinement and a
persistence-only ablation. Existing residual and critical alerts remained
immediate. Unsupported ML warnings and new security findings required three
consecutive ticks. No new threshold grid, physics, or classification policy was
introduced. The ablation's recall was 69.08% versus 79.29% with security signals,
showing that the gain was not solely smoothing.

All original guards stayed fixed: 95% precision floor, at most one-point
precision loss, 1.5% tick FPR cap and at most .25-point FPR increase, no event
coverage regression, bounded delay, and existing downstream accuracy/false-alert
guards. Validation changes were documented before any final data was inspected.
The proposed final corpus reserves new complete runs and stealthy conditions
excluded from development; it remains ungenerated because validation failed.

The combined pipeline, not pure-ML recall, is compared on identical runs.
Detailed metrics, per-attack coverage/delay, guard failures, confusion matrices,
source hashes and manifests are in `outputs/security-detector-study-v1/REPORT.md`.
Original daytime validation FPR differs from the older full-cycle/fault-only
dashboard population. Those percentages must not be conflated.

## Reproduction

Use the existing environment and trusted original Stage 2 and Step 5 artifacts.
Do not overwrite any working model or install additional packages.

```powershell
$env:PYTHONPATH = 'backend'
$env:OMP_NUM_THREADS = '1'
.venv/Scripts/python.exe scripts/study_security_detector.py develop
.venv/Scripts/python.exe scripts/study_security_detector.py refine
.venv/Scripts/python.exe scripts/study_security_detector.py final
.venv/Scripts/python.exe scripts/study_security_detector.py report
.venv/Scripts/python.exe scripts/verify_security_signal_runtime.py
```

Development and refinement have already run here and refuse to overwrite their
frozen selection. Use the saved results. `final` records a rejection without
generating the final set when validation selects nothing. `report` only renders
saved measurements. For an independent reproduction, use a fresh checkout with
the same original model hashes and dependency versions; prerequisite artifact
generation is documented in `accuracy-optimization.md`. All study outputs are
Git-ignored, but no new output is required for production because none was
activated. Do not deploy the three rejected research sidecars.

## Verification and scope

473 backend tests passed, including 13 new focused tests; 134 frontend tests,
TypeScript and production build passed. Eight real application-lifespan API
scenarios used isolated storage and confirmed persisted-signal streaming parity,
injection, detection, uncertainty, bounded automatic jobs and duplicate protection.
The rejected candidates were not wired into production. No new browser workflow
was necessary or claimed. The user's live run and database were untouched.

All original model hashes and all frontend source hashes match the pre-study
manifest. Simulator, fault/attack injection, incident APIs, ShadowTwin and agent
code were not edited. Previous uncommitted work was preserved. No commits or
pushes were made; rollback requires no action.
