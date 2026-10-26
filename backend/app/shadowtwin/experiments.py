"""Explicit prospective experiments; no candidate selection, ranking or inference."""
from collections.abc import Mapping
from dataclasses import dataclass, field

from .foundation import ComparisonFrame, MAX_ADVANCE_TICKS, SimulationSnapshot

SUPPORTED_INTERVENTIONS = {"use_redundant_solar": "solar_sensor",
                           "restore_controller_policy": "controller",
                           "flush_communication": "communication"}


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    component: str
    mechanism: str
    intervention: str
    duration_ticks: int = 30
    checkpoint_id: str = "current-checkpoint"
    parameters: dict = field(default_factory=dict)
    mode: str = "prospective"

    def __post_init__(self):
        for name in ("hypothesis_id", "component", "mechanism", "intervention", "checkpoint_id", "mode"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a nonempty caller-supplied identifier")
        if type(self.duration_ticks) is not int or not 1 <= self.duration_ticks <= MAX_ADVANCE_TICKS:
            raise ValueError(f"duration_ticks must be an integer from 1 to {MAX_ADVANCE_TICKS}")
        if not isinstance(self.parameters, Mapping):
            raise ValueError("parameters must be a mapping")


@dataclass
class ExperimentResult:
    experiment_id: str
    hypothesis_id: str
    suspected_component: str
    hypothesized_mechanism: str
    requested_intervention: str
    checkpoint_id: str
    status: str = "unsupported"
    intervention_status: str = "not_applied"
    experiment_kind: str = "prospective_intervention"
    start_tick: int | None = None
    end_tick: int | None = None  # Exclusive boundary; final row is end_tick - 1.
    execution_tick: int | None = None
    sustained: bool = False
    pre_incident_checkpoint_verified: bool = False
    external_conditions_matched: bool | None = None
    random_states_matched: bool | None = None
    control_telemetry: list[dict] = field(default_factory=list)
    experimental_telemetry: list[dict] = field(default_factory=list)
    comparison_frames: list[ComparisonFrame] = field(default_factory=list)
    observable_differences: list[dict] = field(default_factory=list)
    energy: dict = field(default_factory=dict)
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=lambda: [
        "Prospective behavior from the supplied checkpoint is not retrospective causal verification.",
        "Changed or improved behavior does not prove the suspected component was the original source.",
        "Grid import/export are not modeled; unavailable values remain None.",
    ])


def _deltas(control, experimental):
    """Actual experimental-minus-control values, without scores or weighting."""
    result = {}
    for key in sorted(control.keys() & experimental.keys()):
        a, b = control[key], experimental[key]
        if isinstance(a, Mapping) and isinstance(b, Mapping):
            result[key] = _deltas(a, b)
        elif type(a) in (int, float) and type(b) in (int, float):
            result[key] = b - a
        elif a is None or b is None:
            result[key] = None
        elif a != b:
            result[key] = {"control": a, "experimental": b}
    return result


def _random_states(branch):
    # RNG state is used only to audit matching conditions, never source selection.
    return tuple(getattr(branch._simulator, name).getstate() for name in (
        "_weather", "_measurement", "_communication", "_redundant_measurement", "_attack_random", "_security_random"))


def run_experiment(snapshot: SimulationSnapshot | None, hypothesis: Hypothesis, *, experiment_id: str):
    """Run one caller-defined hypothesis against an untouched clone of the same state.

    Supported controls route existing measurements or the existing nominal command
    before physical simulation. Queue flushing reuses existing correction behavior
    without cancelling any schedules. No hidden source/schedule lookup occurs here.
    """
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise ValueError("experiment_id must be a nonempty string")
    result = ExperimentResult(experiment_id, hypothesis.hypothesis_id, hypothesis.component,
                              hypothesis.mechanism, hypothesis.intervention, hypothesis.checkpoint_id)
    if hypothesis.mode != "prospective":
        result.experiment_kind = "unsupported_checkpoint_provenance"
        result.reason = "Historical/pre-incident checkpoint provenance is not verified by this foundation; no time travel was attempted."
        return result
    if snapshot is None:
        result.experiment_kind = "unsupported_missing_checkpoint"
        result.reason = "An existing current-state checkpoint is required."
        return result
    if not isinstance(snapshot, SimulationSnapshot):
        raise TypeError("snapshot must be a SimulationSnapshot")
    if snapshot.next_tick + hypothesis.duration_ticks > snapshot._max_tick:
        raise ValueError("Experiment duration exceeds the captured simulation horizon")
    result.start_tick = result.end_tick = snapshot.next_tick
    if hypothesis.intervention != "none" and SUPPORTED_INTERVENTIONS.get(hypothesis.intervention) != hypothesis.component:
        result.reason = "The requested component/intervention pair is unsupported. No alternative was selected."
        return result
    if hypothesis.parameters:
        result.reason = "These interventions accept no optional parameters; the request was not silently changed."
        return result
    control, experimental = snapshot.fork("control"), snapshot.fork("experimental")
    initial_random_match = _random_states(control) == _random_states(experimental)
    options = {}
    if hypothesis.intervention in ("use_redundant_solar", "restore_controller_policy"):
        options[hypothesis.intervention] = True
        result.sustained = True
        result.intervention_status = "sustained_for_experiment"
    elif hypothesis.intervention == "flush_communication":
        experimental._simulator.flush_communication()
        result.execution_tick = experimental.next_tick
        result.intervention_status = "applied_once"
        result.warnings.append("Communication buffers were flushed once. Ongoing manipulation remains active and may immediately refill them; recovery is not asserted.")
    else:
        result.intervention_status = "not_requested"
    if hypothesis.intervention == "use_redundant_solar":
        result.warnings.append("The existing redundant solar sensor is an alternative measurement, not an independently authenticated or guaranteed healthy reference.")
    if hypothesis.intervention == "restore_controller_policy":
        result.warnings.append("The nominal controller still uses the received inputs and applied configuration; upstream manipulation and inverter disturbances remain effective.")
    try:
        result.control_telemetry = control.advance(hypothesis.duration_ticks)
        result.experimental_telemetry = experimental.advance(hypothesis.duration_ticks, **options)
        if options:
            result.execution_tick = snapshot.next_tick
    except Exception as error:
        result.status = "failed"
        result.intervention_status = "failed"
        result.reason = f"Branch advancement failed ({type(error).__name__}); no recovery conclusion is available."
        result.control_telemetry = []
        result.experimental_telemetry = []
        result.end_tick = None
        result.sustained = False
        if options:
            result.execution_tick = snapshot.next_tick if experimental.next_tick > snapshot.next_tick else None
        return result
    for a, b in zip(result.control_telemetry, result.experimental_telemetry):
        frame = ComparisonFrame.from_rows(experiment_id, {"control": a, "experimental": b})
        result.comparison_frames.append(frame)
        result.observable_differences.append({"tick": frame.tick, "experimental_minus_control":
            _deltas(frame.telemetry["control"], frame.telemetry["experimental"])})
    result.external_conditions_matched = all(
        all(a[key] == b[key] for key in ("elapsed_seconds", "hour", "irradiance", "actual_solar_kw", "demand_kw"))
        for a, b in zip(result.control_telemetry, result.experimental_telemetry))
    result.random_states_matched = initial_random_match and _random_states(control) == _random_states(experimental)
    if not result.external_conditions_matched or not result.random_states_matched:
        result.warnings.append("Operating conditions or random-stream consumption diverged; observed differences cannot be attributed solely to the requested intervention.")
    result.limitations.append("Matching RNG states do not guarantee common disturbances for every possible future intervention; conditional random draws remain unchanged in the simulator.")
    a, b = control.energy_snapshot(), experimental.energy_snapshot()
    result.energy = {"control": a, "experimental": b, "experimental_minus_control": _deltas(a, b),
                     "scope": "Existing cumulative energy-ledger measurements at the same ending tick; shared pre-checkpoint history is retained."}
    result.end_tick = experimental.next_tick
    result.status = "completed"
    return result
