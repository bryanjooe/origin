"""Approved observations for planning; never accept simulator/checkpoint objects."""
from collections.abc import Mapping
from dataclasses import dataclass
import math

from app.explainability.evidence import SIGNAL_NODES
from app.propagation.investigation import SECURITY_LAYERS


# Existing observable security-log flags, not injection metadata or new thresholds.
LOG_SIGNALS = {
    "solar_sensors_agree": (False, "solar_sensor"),
    "command_policy_consistent": (False, "controller"),
    "duplicate_sequence": (True, "communication"),
    "out_of_order_sequence": (True, "communication"),
    "config_integrity_match": (False, "firmware"),
    "battery_sensors_agree": (False, "battery_sensor"),
}
PHASE1_GROUPS = {"sensor": tuple(SECURITY_LAYERS["Sensor"]),
                 "communication": ("communication",), "controller": ("controller",),
                 "firmware": ("firmware",), "inverter": ("inverter",)}


def _record(value):
    return value if isinstance(value, Mapping) else {}


def _tick(value):
    return value if type(value) is int and value >= 0 else None


def _identifier(value):
    return value if isinstance(value, str) and 0 < len(value) <= 256 else None


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True)
class Observation:
    signal: str
    tick: int
    value: float | bool
    threshold: float | None
    unit: str | None
    evidence_id: str | None
    provenance: str

    def __post_init__(self):
        if _tick(self.tick) is None or self.provenance not in ("current_detection", "current_security_log", "incident_record"):
            raise ValueError("Observations require a valid recorded tick and approved provenance")
        if self.signal in LOG_SIGNALS:
            if type(self.value) is not bool or self.value != LOG_SIGNALS[self.signal][0] or self.threshold is not None:
                raise ValueError("Security-log observations require the existing abnormal flag")
        elif self.signal not in SIGNAL_NODES or not (_number(self.value) and _number(self.threshold) and self.threshold > 0 and self.value > self.threshold):
            raise ValueError("Residual observations must exceed their supplied existing rule limit")
        if self.unit is not None and (not isinstance(self.unit, str) or len(self.unit) > 80):
            raise ValueError("Observation units must be bounded text")
        if self.evidence_id is not None and self.evidence_id != f"t{self.tick}:{self.signal}":
            raise ValueError("Evidence IDs must match the existing recorded-evidence format")

    @property
    def components(self):
        return (LOG_SIGNALS[self.signal][1],) if self.signal in LOG_SIGNALS else tuple(SIGNAL_NODES[self.signal])


MODEL_FIELDS = {
    "anomaly": ("tick", "anomaly_score", "ml_status", "rule_status", "combined_status", "warning_threshold", "critical_threshold"),
    "phase1": ("tick", "predicted_source", "confidence", "confidence_kind"),
    "stage_b": ("available", "status", "origin", "origin_confidence", "nature_verdict", "nature_confidence", "confidence_kind", "inference_tick", "window_start_tick", "window_end_tick"),
}


@dataclass(frozen=True)
class ModelRecord:
    """Approved original model values for reporting, never extra selection weights."""
    name: str
    scope: str
    fields: tuple
    candidates: tuple = ()

    def __post_init__(self):
        if self.name not in MODEL_FIELDS or self.scope not in ("current", "historical_or_undated"):
            raise ValueError("Invalid model record provenance")
        if type(self.fields) is not tuple or len(self.fields) > len(MODEL_FIELDS[self.name]):
            raise ValueError("Model fields must be a bounded immutable projection")
        seen = set()
        if any(type(pair) is not tuple or len(pair) != 2 for pair in self.fields):
            raise ValueError("Model field pairs must be immutable")
        for key, value in self.fields:
            if key not in MODEL_FIELDS[self.name] or key in seen:
                raise ValueError("Unapproved model field")
            seen.add(key)
            if not (value is None or type(value) is bool or _number(value) or (isinstance(value, str) and len(value) <= 120)):
                raise ValueError("Model values must be finite primitives")
        labels = PHASE1_GROUPS if self.name == "phase1" else SECURITY_LAYERS
        if type(self.candidates) is not tuple or len(self.candidates) > 10:
            raise ValueError("Model candidates must be a bounded immutable projection")
        if any(type(pair) is not tuple or len(pair) != 2 for pair in self.candidates):
            raise ValueError("Candidate pairs must be immutable")
        for label, score in self.candidates:
            if label not in (*labels, "normal", "Normal", "unknown", "Unknown") or not _number(score) or not 0 <= score <= 1:
                raise ValueError("Invalid reported model candidate")


def _model_record(name, record, current):
    if not record:
        return None
    fields = tuple((key, value) for key in MODEL_FIELDS[name] if key in record
                   and ((value := record[key]) is None or type(value) is bool or _number(value)
                        or (isinstance(value, str) and len(value) <= 120)))
    labels = PHASE1_GROUPS if name == "phase1" else SECURITY_LAYERS
    candidates = []
    for candidate in record.get("candidates" if name == "phase1" else "origin_candidates", [])[:10] if isinstance(record.get("candidates" if name == "phase1" else "origin_candidates"), list) else []:
        candidate = _record(candidate)
        label, score = candidate.get("source" if name == "phase1" else "layer"), candidate.get("confidence")
        if label in (*labels, "normal", "Normal", "unknown", "Unknown") and _number(score) and 0 <= score <= 1:
            candidates.append((label, score))
    return ModelRecord(name, "current" if current else "historical_or_undated", fields, tuple(candidates))


@dataclass(frozen=True)
class ObservableContext:
    """Detached, immutable allowlist. current_tick is the runtime's NEXT tick.

    Latest processed observations therefore have tick == current_tick - 1.
    Construct via observable_context(runtime.state(), store.incident(id)).
    The caller must read those records under its existing runtime lock.
    """
    run_id: str | None = None
    current_tick: int | None = None
    incident_id: str | None = None
    incident_run_id: str | None = None
    incident_start_tick: int | None = None
    incident_end_tick: int | None = None
    current_status: str | None = None
    snapshot_available: bool | None = None
    current_observations: tuple[Observation, ...] = ()
    historical_observations: tuple[Observation, ...] = ()
    phase1_prediction: str | None = None
    stage_b_origin: str | None = None
    stage_b_nature: str | None = None
    phase1_components: tuple[str, ...] = ()
    stage_b_components: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    model_records: tuple[ModelRecord, ...] = ()

    def __post_init__(self):
        if type(self.model_records) is not tuple or len(self.model_records) > 3 or any(type(item) is not ModelRecord for item in self.model_records) or len({item.name for item in self.model_records}) != len(self.model_records):
            raise ValueError("Use at most three unique approved model records")
        for key in ("run_id", "incident_id", "incident_run_id"):
            value = getattr(self, key)
            if value is not None and _identifier(value) is None:
                raise ValueError(f"Invalid {key}")
        for key in ("current_tick", "incident_start_tick", "incident_end_tick"):
            value = getattr(self, key)
            if value is not None and _tick(value) is None:
                raise ValueError(f"Invalid {key}")
        if self.current_status not in (None, "normal", "warning", "critical"):
            raise ValueError("Unknown anomaly status")
        if self.snapshot_available is not None and type(self.snapshot_available) is not bool:
            raise ValueError("Snapshot availability must be explicit or unknown")
        for records in (self.current_observations, self.historical_observations):
            if type(records) is not tuple or len(records) > 256 or any(type(item) is not Observation for item in records):
                raise ValueError("Use bounded immutable approved observations")
        if any(self.current_tick is None or item.tick != self.current_tick - 1 for item in self.current_observations):
            raise ValueError("Current observations must match the latest processed tick")
        # Hints are accepted groups, not untrusted strings, hidden labels or scores.
        if self.phase1_prediction not in (*PHASE1_GROUPS, "normal", "unknown", None):
            raise ValueError("Invalid Phase 1 prediction")
        if self.stage_b_origin not in (*SECURITY_LAYERS, "Unknown", None):
            raise ValueError("Invalid Stage B prediction")
        if self.stage_b_nature not in (None, "Normal", "Accidental fault", "Cyber attack", "Undetermined"):
            raise ValueError("Invalid Stage B nature")
        if self.phase1_components != PHASE1_GROUPS.get(self.phase1_prediction, ()):
            raise ValueError("Phase 1 components must retain their actual candidate group")
        if self.stage_b_components != tuple(SECURITY_LAYERS.get(self.stage_b_origin, ())):
            raise ValueError("Stage B components must retain their actual candidate group")
        allowed = {"historical_incident_current_state_only", "incident_timing_unknown", "undated_or_stale_current_detection_ignored", "stale_ai_context_ignored", "run_identifier_missing"}
        if type(self.limitations) is not tuple or any(item not in allowed for item in self.limitations):
            raise ValueError("Use approved context limitation codes")


def observable_context(system_state, incident=None):
    """Project existing API/runtime records without copying arbitrary nested data.

    Hidden metadata, schedules, source labels outside official prediction records,
    and all simulator/checkpoint objects are neither inspected nor retained.
    Missing or invalid residual observations are ignored, never filled in.
    """
    if not isinstance(system_state, Mapping) or (incident is not None and not isinstance(incident, Mapping)):
        raise TypeError("Pass observable record mappings, never simulator or snapshot objects")
    incident = _record(incident)
    run_id, current_tick = _identifier(system_state.get("run_id")), _tick(system_state.get("next_tick"))
    incident_id, incident_run_id = _identifier(incident.get("id")), _identifier(incident.get("run_id"))
    start, end = _tick(incident.get("first_observed_tick")), _tick(incident.get("last_alert_tick"))
    if start is not None and end is not None and end < start:
        raise ValueError("Incident observation window is reversed")
    limitations = []
    if run_id is None:
        limitations.append("run_identifier_missing")
    historical = bool(incident_id and ((run_id and incident_run_id and run_id != incident_run_id)
                      or (end is not None and current_tick is not None and end < current_tick - 1)
                      or incident.get("status") in ("resolved", "interrupted")))
    if historical:
        limitations.append("historical_incident_current_state_only")
    if incident_id and (start is None or end is None or incident_run_id is None):
        limitations.append("incident_timing_unknown")
    latest = current_tick - 1 if current_tick is not None else None
    detection = _record(system_state.get("anomaly"))
    detection_current = latest is not None and latest >= 0 and _tick(detection.get("tick")) == latest
    status = detection.get("combined_status") if detection_current else None
    if status not in ("normal", "warning", "critical"):
        status = None
    if detection and not detection_current:
        limitations.append("undated_or_stale_current_detection_ignored")
    current, older = [], []

    def read_checks(items, tick, provenance, destination):
        if not isinstance(items, (list, tuple)):
            return
        if len(items) > 256:
            raise ValueError("At most 256 supplied evidence records are supported")
        for raw in items:
            raw = _record(raw)
            at = _tick(raw.get("tick", tick))
            if at is None:
                continue
            if provenance == "current_detection" and at != latest:
                continue
            if provenance == "incident_record" and run_id and incident_run_id == run_id and current_tick is not None and at >= current_tick:
                continue
            signal = raw.get("signal")
            if not isinstance(signal, str) or signal not in SIGNAL_NODES:
                continue
            try:
                destination.append(Observation(signal, at, raw.get("value"), raw.get("threshold"),
                    raw.get("unit") if isinstance(raw.get("unit"), str) else None,
                    raw.get("id") if isinstance(raw.get("id"), str) else None, provenance))
            except ValueError:
                continue
    if detection_current:
        read_checks(detection.get("residual_checks"), latest, "current_detection", current)
    read_checks(incident.get("evidence"), None, "incident_record", older)
    historical_records = []
    for item in older:
        if run_id and incident_run_id == run_id and item.tick == latest:
            current.append(item)
        else:
            historical_records.append(item)
    if historical_records:
        limitations.append("historical_incident_current_state_only")
    telemetry = _record(system_state.get("telemetry"))
    if latest is not None and latest >= 0 and _tick(telemetry.get("tick")) == latest:
        security = _record(telemetry.get("security_telemetry"))
        for signal, (abnormal, _) in LOG_SIGNALS.items():
            if type(security.get(signal)) is bool and security[signal] == abnormal:
                current.append(Observation(signal, latest, abnormal, None, None, None, "current_security_log"))
    source = _record(system_state.get("source"))
    models = _record(system_state.get("models"))
    phase1 = source.get("predicted_source") if latest is not None and _tick(source.get("tick")) == latest and _record(models.get("source")).get("available") is True else None
    if phase1 not in (*PHASE1_GROUPS, "normal", "unknown"):
        phase1 = None
    assessment = _record(incident.get("security_attribution"))
    stage_current = (run_id is not None and incident_run_id == run_id and latest is not None
                     and _tick(assessment.get("window_end_tick")) == latest and assessment.get("available") is True)
    origin = assessment.get("origin") if stage_current else None
    nature = assessment.get("nature_verdict") if stage_current else None
    if assessment and not stage_current:
        limitations.append("stale_ai_context_ignored")
    if origin not in (*SECURITY_LAYERS, "Unknown"):
        origin = None
    if nature not in ("Normal", "Accidental fault", "Cyber attack", "Undetermined"):
        nature = None
    return ObservableContext(run_id, current_tick, incident_id, incident_run_id, start, end, status,
        (system_state.get("runtime_error") is None) if run_id and current_tick is not None else None,
        tuple(sorted(set(current), key=lambda x: (x.signal, x.provenance, x.evidence_id or ""))),
        tuple(sorted(set(historical_records), key=lambda x: (x.tick, x.signal, x.evidence_id or ""))),
        phase1, origin, nature, PHASE1_GROUPS.get(phase1, ()), tuple(SECURITY_LAYERS.get(origin, ())), tuple(sorted(set(limitations))),
        tuple(item for item in (_model_record("anomaly", detection, detection_current),
            _model_record("phase1", source, latest is not None and _tick(source.get("tick")) == latest),
            _model_record("stage_b", assessment, stage_current)) if item is not None))
