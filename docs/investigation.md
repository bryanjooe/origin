# Stage 4 investigation contract

## Inputs and incident lifecycle

`IncidentTracker.update(telemetry_row, anomaly_result, source_result=None)` consumes
one tick at a time. Rows must be consecutive and time-ordered; both model results
must match the row's tick and simulated time. The anomaly result is required and
must come from the existing detector. Model outputs are trusted internal records,
not an endpoint for arbitrary client-supplied diagnoses. The offline `investigate`
helper replays aligned sequences through the same streaming implementation.

Only the detector's `combined_status` opens or sustains an incident. Neither unmet
demand nor a classifier source prediction alone opens one. Defaults:

- Three consecutive warnings confirm an incident. Pending observations are retained,
  so the first-observed tick precedes the confirmation/detection tick by two ticks.
- Critical alerts confirm immediately, including any immediately preceding pending
  warning observations.
- Five consecutive non-alert ticks resolve the incident. Shorter quiet gaps remain
  part of the same incident. A later alert after resolution opens a new incident.
- An incident still active at the end of a run remains open. Reset clears tracker
  history and starts deterministic IDs again; it is separate from simulator reset.

`confirmation_delay_seconds` measures alert confirmation delay, **not** delay from
hidden fault injection. The tracker never reads the injection schedule. Simulated
time is used throughout; there are no fabricated wall-clock timestamps.

## Diagnosis selection and uncertainty

The representative diagnosis comes from the alert tick with the highest Isolation
Forest score in the incident (latest tick wins ties), using that tick's actual source
classifier output. This fixed convention is not selection based on known fault truth.
The representative tick, peak score, latest alert-time diagnosis and hypothesis
changes are all retained. Quiet recovery samples do not replace the diagnosis.

If no source model is provided, the source is explicitly Unknown and availability
is false. A classifier's Normal result during an active alert is also reported as
Unknown due to conflicting evidence, retaining the original `model_predicted_source`
and candidates. An already Unknown result stays Unknown. Accepted confidence is
the classifier's actual uncalibrated score, not a newly synthesized incident-level
probability. Scores are not averaged across correlated ticks or treated as causal
confidence.

One incident can contain changing or competing hypotheses, and merged alerts do not
establish a single common cause. Later stages can add more sophisticated grouping.
No source model is retrained and no new accuracy claim is made at this stage.

## Evidence and explanations

The tracker copies an explicit allowlist of current solar/SOC measurements, demand,
delivery, battery bus power, commands, packet values/timestamps, inverter request/
output and applied configuration. Hidden actual PV, physical SOC/stored energy,
generator labels, seeds, severity, durations, schedules and future telemetry are not
read. Tests verify that changing hidden fields leaves complete reports unchanged.
State snapshots are deep copies and contain only evidence observed by `as_of_tick`.

Actual triggered residual records from the anomaly/localization models supply
signal, value, threshold and units. The tracker rejects non-finite values and checks
that reported residual values exceed their limits. Duplicate checks for the same
tick/signal are merged; all subsequent observed values are retained. Check records
are observations from the existing feature calculations, not independent proof of
the predicted source.

Unmet demand > 0.1 kW is separately recorded as an **observed impact**. It never
triggers an incident and is explicitly compatible with normal resource scarcity.
The first observation of each symptom creates a timeline entry; changes in source
hypothesis, incident confirmation and alert clearance create separate events.
Events sharing a tick cannot establish a causal sequence.

Explanations use deterministic templates with actual numeric evidence and model
scores. They include why the detector flagged the system, deviations, representative
source and alternatives, symptom sequence, potentially affected components,
diagnostic checks, and recovery/causality caveats. There is no external LLM call,
invented evidence, SHAP claim or fabricated feature importance. ML-only alerts can
have no residual explanation beyond their multivariate anomaly score.

Diagnostic checks describe software-only comparisons: independent irradiance/SOC/
AC metering, packet timestamp verification, policy replay, and intended-versus-
applied configuration comparisons. They are recommendations; generating a report
does not execute a correction.

## Dependency graph and node inspection

Each report includes the full known NetworkX dependency graph. Accepted source
classes map to candidate component nodes. A Sensor prediction uses solar/battery
symptom evidence to select candidate sensor nodes, retaining both possibilities
when evidence cannot distinguish them. Unknown-source incidents mark observed
symptoms but have no invented source node or suspected path.

For each candidate source and observed symptom, one directed shortest dependency
path is shown when reachable. Feedback cycles are allowed in the topology; shortest
paths do not loop. Only edges on those paths are marked suspected. Each suspected
edge references concrete symptom evidence IDs and declares its scope as
"downstream symptom on a structural path". Intermediate transmission is explicitly
not directly established. A path to an observed shortage is compatibility evidence,
not proof that the candidate caused the shortage. Other routes/explanations may exist.

Known dependencies retain their original descriptions and edge kinds. The shared
topology is never mutated by an investigation. Nodes provide candidate-source,
observed-symptom and potentially-affected flags, evidence references, relevant
per-tick telemetry and symptom events for later frontend inspection. The graph is
historical over the incident; highlighting in a resolved report does not mean a
component remains faulty at its final tick. Affected intermediate nodes are
potentially involved, not individually proven abnormal.

## Exports, limitations and use

After training Stages 2/3, add `--investigate` to the simulator command shown in
README. It requires `--anomaly-model`; `--source-model` is optional. Output
`incidents.json` is separate from physical telemetry, predictions and hidden truth.
It contains complete evidence, observable samples, explanations and graph details.
The checked-in `stage4-examples.json` contains compact measured summaries retaining
latest evidence per signal and final node telemetry, not all per-tick observations.

```python
from app.explainability.incidents import IncidentTracker

tracker = IncidentTracker(confirmation_ticks=3, recovery_ticks=5)
# For each live tick, pass that tick's telemetry and real model outputs:
# tracker.update(row, anomaly_result, source_result)
reports = tracker.reports()
```

Current limits: retained observations grow with incident length, incident IDs are
local to a tracker, and alert-based resolution can occur while an unobservable fault
persists. Model mistakes can yield incorrect or Unknown origins; graphs preserve
that uncertainty rather than consulting hidden truth. There is no persistent
database, live API, interactive Cytoscape UI or end-to-end accuracy benchmark yet.
Those remain for subsequent stages. Existing Stage 2/3 held-out metrics remain
per-tick detector/classifier measurements and must not be relabeled as incident
performance.
