# Accuracy optimization study (accuracy-v1)

The bounded study finished without a qualifying candidate. **No active model,
feature extractor, inference threshold, calibration, frontend or deployment
configuration was changed.** The original trained artifacts remain available.
The measured results, confusion matrices and limitations are in
`outputs/accuracy-optimization/REPORT.md` and `comparison.csv`.

The experiment tested four Isolation Forest warning thresholds, two small Random
Forest localization adjustments, one localization confidence-policy comparator,
and two Stage B nature thresholds. Selection used validation only. Final
rejection did not cause reselection, additional fitting, or another final test.

## Findings

The detector threshold candidate improved fresh-test ML recall from 29.09% to
34.51% and F1 from 44.54% to 50.38%, but precision fell from 95.02% to 93.31%,
below the declared 95% floor. False positives increased from 0.81% to 1.32%.
The Stage B candidate improved nature macro-F1 from 53.62% to 54.89%, but
accepted-prediction accuracy fell from 85.71% to 83.33%, exceeding the declared
one-percentage-point loss limit. Localization candidates failed validation.

The original headline figures were reproduced exactly, but these fresh-test
figures use new runs and different exposure and must not be directly compared
to historical dashboard percentages. The dashboard continues to show original
model reports because no candidate was accepted.

Constant controller/configuration features have zero splits in the normal-only
Isolation Forest. Existing residual rules cover these conditions separately.
Weak attacks also suffer from upstream gating: authentication/sequence and
redundancy observations used by Stage B are absent from the anomaly feature
schema. A nature-threshold change cannot repair a missed incident. Inverter
delay, weak operating effects, and honest abstention contribute to localization
errors. Some faults and attacks have identical observations, so intent cannot
always be identified.

## Reproduce using the current trusted artifacts

From the repository root, using the existing environment and dependencies:

```powershell
$env:PYTHONPATH = 'backend'
$env:OMP_NUM_THREADS = '1'
.venv/Scripts/python.exe scripts/optimize_accuracy.py reproduce
.venv/Scripts/python.exe scripts/optimize_accuracy.py develop
.venv/Scripts/python.exe scripts/optimize_accuracy.py final
.venv/Scripts/python.exe scripts/optimize_accuracy.py report
.venv/Scripts/python.exe scripts/verify_accuracy_runtime.py
```

The first three phases have already run in this checkout. Development refuses
to overwrite a frozen selection; final evaluation refuses to reopen its holdout.
Use the saved results here. `report` derives tables without fitting or selection.
For an independent reproduction, use a separate fresh checkout/output directory,
preserve the same versions/configuration, and do not treat the now-known final
seeds as a new pristine test. Further optimization needs a different predeclared
holdout; changing these guards after inspecting results is not valid promotion.

Required trusted inputs are the Stage 2/3 artifacts and CSVs, and the Phase 2
Step 5 regular/dedicated-stealth bundles, frozen split manifests and observable
window caches under `outputs/step5/candidates/`. Original hashes are recorded in
`original_manifest.json`; full model metadata and feature versions are recorded
in `artifact_metadata.json`. No network or new packages are required here.

## Fresh checkout and ignored artifacts

All `outputs/` artifacts are Git-ignored. Do not deploy a research model by
copying its path into an environment variable. This study accepted none, so a
fresh deployment continues to use the existing supported model generation and
`scripts/run_reliable_api.ps1` configuration.

To reproduce missing prerequisite artifacts in a **fresh checkout**, first run
the existing documented training commands:

```powershell
$env:PYTHONPATH = 'backend'
$env:OMP_NUM_THREADS = '1'
.venv/Scripts/python.exe -m app.detection
.venv/Scripts/python.exe -m app.localization
.venv/Scripts/python.exe -m app.security_analysis --repeats 9 --ticks 240 --seed 72100 --output-dir outputs/stage5
```

Preserve that Stage B bundle in a new `outputs/step5/original/` directory before
running `scripts/evaluate_stage_b_reliability.py` with its existing defaults
(seed 841600, repeats 9, 240 ticks, 1,200 extra normal runs). It creates the
regular/dedicated-stealth artifacts and caches consumed by this study. This
prerequisite is substantially more expensive than the bounded threshold study;
do not regenerate or overwrite an existing working bundle merely to inspect
the saved report. Verify `outputs/step5/promoted.json` and its acceptance guards
before using the existing launch script. Different library versions or hashes
require a new declared baseline rather than assuming bitwise reproducibility.

Rollback requires no action: no candidate was activated, and original files and
loading settings are unchanged. The `accepted/` research directory contains
retained-original copies labeled `original-retained`, not approved new models.

## Validation and compatibility

Final regression: 460 backend tests passed (four existing warnings), 134
frontend tests passed, TypeScript passed, production build passed. Three new
tests prevent headline-score gains from bypassing precision, false-alert and
class-preservation guards. No existing tests were edited. No lint script is
configured.

`verify_accuracy_runtime.py` uses the actual application lifespan with an
isolated in-memory database and the unchanged active bundle. Nine supported
normal/attack/fault cases verify injection, inference, persistence, uncertainty,
automatic investigation, duplicate prevention and existing budgets. It records
missed detections honestly. The user's live run and database are untouched.
Browser verification inspected Model Evaluation and Fault Investigation,
including the original graph, Stage B assessment and agent/manual ShadowTwin
panels. Injection cases were API integration checks, not nine manual browser
demonstrations. The existing custom frontend was not edited.

No scientifically justified deployed accuracy improvement was achieved. New
feature and coverage work is deferred rather than tuned against the consumed
final evaluation set. No commits, pushes or new dependencies were introduced.
