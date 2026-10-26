"""Typed request and response contracts for API v1."""
from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.fault_injection import Fault, FaultKind
from app.fault_injection.engine import MODES
from app.simulator import GridConfig
from app.propagation import build_topology


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GridConfigInput(StrictModel):
    tick_seconds: float = Field(default=60.0, gt=0)
    start_hour: float = Field(default=10.0, ge=0, lt=24)
    solar_capacity_kw: float = Field(default=12.0, gt=0)
    dc_voltage_v: float = Field(default=400.0, gt=0)
    battery_capacity_kwh: float = Field(default=24.0, gt=0)
    initial_soc_pct: float = Field(default=60.0, ge=0, le=100)
    reserve_soc_pct: float = Field(default=10.0, ge=0, le=100)
    charge_limit_kw: float = Field(default=5.0, ge=0)
    discharge_limit_kw: float = Field(default=5.0, ge=0)
    charge_efficiency: float = Field(default=0.95, gt=0, le=1)
    discharge_efficiency: float = Field(default=0.95, gt=0, le=1)
    inverter_efficiency: float = Field(default=0.96, gt=0, le=1)
    inverter_limit_kw: float = Field(default=15.0, gt=0)
    base_demand_kw: float = Field(default=7.0, gt=0)
    communication_delay_ticks: StrictInt = Field(default=0, ge=0)
    packet_loss_probability: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_simulator_constraints(self) -> "GridConfigInput":
        try:
            GridConfig(**self.model_dump())
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        return self


class FaultScheduleInput(StrictModel):
    # Keep JSON enum values as strings, then validate them with the simulator enum.
    kind: str
    mode: str
    severity: float = Field(default=0.7, gt=0, le=1)
    duration_ticks: StrictInt = Field(default=30, ge=1)
    start_tick: StrictInt = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_fault(self) -> "FaultScheduleInput":
        try:
            Fault(
                kind=self.kind,
                mode=self.mode,
                start_tick=self.start_tick,
                duration_ticks=self.duration_ticks,
                severity=self.severity,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        return self


class RunCreateInput(StrictModel):
    config: GridConfigInput = Field(default_factory=GridConfigInput)
    seed: StrictInt = 42
    fault: FaultScheduleInput | None = None


class RunErrorResponse(StrictModel):
    code: str
    message: str


class RunResponse(StrictModel):
    run_id: str
    status: Literal["ready", "complete"]
    seed: int
    current_tick: int
    max_ticks: int
    tick_seconds: float
    created_at: str
    updated_at: str
    error: RunErrorResponse | None = None


class RunStatusResponse(RunResponse):
    config: GridConfigInput


class AdvanceInput(StrictModel):
    ticks: StrictInt = Field(ge=1, le=1000)


class AdvanceResponse(StrictModel):
    run_id: str
    status: Literal["ready", "complete"]
    advanced_ticks: int
    current_tick: int


class CorrectionResponse(StrictModel):
    run_id: str
    corrected: bool
    current_tick: int


class FaultScheduleResponse(StrictModel):
    run_id: str
    scheduled: bool
    start_tick: int


class FaultModeInfo(StrictModel):
    name: str
    description: str


class FaultFamilyInfo(StrictModel):
    name: str
    modes: list[FaultModeInfo]


class FaultParameters(StrictModel):
    severity_min_exclusive: float = 0.0
    severity_max_inclusive: float = 1.0
    duration_ticks_min: int = 1
    start_tick_min: int = 0
    start_tick_relation: str


class FaultCatalogResponse(StrictModel):
    fault_types: list[FaultFamilyInfo]
    parameters: FaultParameters


class ControllerInputs(StrictModel):
    source_tick: int
    solar_kw: float
    soc_pct: float
    demand_kw: float


class TelemetryRow(StrictModel):
    tick: int
    elapsed_seconds: float
    hour: float
    irradiance: float
    expected_solar_kw: float
    actual_solar_kw: float
    solar_voltage_v: float
    solar_current_a: float
    measured_solar_kw: float
    measured_soc_pct: float
    measured_solar_voltage_v: float
    measured_solar_current_a: float
    battery_soc_pct: float
    battery_energy_kwh: float
    battery_power_kw: float
    battery_delta_kwh: float
    battery_loss_kwh: float
    demand_kw: float
    delivered_kw: float
    unmet_demand_kw: float
    controller_inputs: ControllerInputs | None
    controller_rule: str
    controller_command_kw: float
    nominal_command_kw: float
    applied_reserve_soc_pct: float
    applied_discharge_limit_kw: float
    config_integrity_ok: bool
    inverter_requested_kw: float
    inverter_actual_kw: float
    inverter_loss_kw: float
    curtailed_dc_kw: float
    excess_ac_kw: float
    message_source_tick: int | None
    message_age_seconds: float | None
    communication_latency_seconds: float
    packet_dropped: bool
    telemetry_available: bool


class TelemetryResponse(StrictModel):
    run_id: str
    start_tick: int
    end_tick: int
    rows: list[TelemetryRow]


class ControllerLog(StrictModel):
    tick: int
    elapsed_seconds: float
    controller_inputs: ControllerInputs | None
    controller_rule: str
    controller_command_kw: float
    nominal_command_kw: float
    applied_reserve_soc_pct: float
    applied_discharge_limit_kw: float
    config_integrity_ok: bool
    inverter_requested_kw: float
    inverter_actual_kw: float
    message_source_tick: int | None
    message_age_seconds: float | None
    communication_latency_seconds: float
    packet_dropped: bool
    telemetry_available: bool


class ControllerLogsResponse(StrictModel):
    run_id: str
    start_tick: int
    end_tick: int
    logs: list[ControllerLog]


class TopologyNode(StrictModel):
    id: str
    label: str


class TopologyEdge(StrictModel):
    source: str
    target: str
    kind: str
    dependency: str
    suspected: bool


class TopologyResponse(StrictModel):
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]


class DownstreamResponse(StrictModel):
    component: str
    downstream: list[str]


class ExportMetadata(StrictModel):
    format: Literal["csv", "json"]
    media_type: str
    tick_count: int
    start_tick: int
    end_tick: int
    generation: Literal["on_demand"]
    download_path: str
    authorization_required: bool


class ExportListResponse(StrictModel):
    run_id: str
    max_export_ticks: int
    exports: list[ExportMetadata]


class ResultMetadataItem(StrictModel):
    artifact_type: Literal["telemetry", "controller_logs", "topology_snapshot", "output_summary"]
    storage_type: Literal["file", "derived", "json"]
    tick_start: int | None
    tick_end: int | None
    media_type: str
    size_bytes: int
    sha256: str | None
    output_summary: dict[str, Any] | None


class ResultMetadataResponse(StrictModel):
    run_id: str
    artifacts: list[ResultMetadataItem]


class HealthResponse(StrictModel):
    status: Literal["ok", "ready"]


IncidentStatus = Literal["open", "investigating", "resolved", "closed"]

_GROUND_TRUTH_KEYS = {
    "scenario_ground_truth", "ground_truth", "faults", "fault_schedule",
    "fault_schedules", "fault_type", "fault_kind", "fault_mode",
    "fault_severity", "fault_label", "labels",
}


def _validate_observed_evidence(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("observed_evidence must be a JSON object")
    try:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("observed_evidence must contain finite JSON values") from exc
    if len(encoded.encode("utf-8")) > 65_536:
        raise ValueError("observed_evidence exceeds 65536 bytes")

    def check_keys(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
                if normalized in _GROUND_TRUTH_KEYS:
                    raise ValueError("observed_evidence cannot contain scenario ground-truth fields")
                check_keys(child)
        elif isinstance(item, list):
            for child in item:
                check_keys(child)

    check_keys(value)
    return value


class IncidentCreateInput(StrictModel):
    simulation_run_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    affected_component: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=4000)
    observed_evidence: dict[str, Any] = Field(default_factory=dict)
    priority: str | None = Field(default=None, max_length=40)
    investigation_status: IncidentStatus = "open"

    @field_validator("observed_evidence")
    @classmethod
    def validate_evidence(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_observed_evidence(value)

    @field_validator("simulation_run_id")
    @classmethod
    def validate_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return str(UUID(value))
        except ValueError as exc:
            raise ValueError("simulation_run_id must be a UUID") from exc

    @model_validator(mode="after")
    def reject_blank_required_fields(self) -> "IncidentCreateInput":
        for name in ("title", "affected_component", "category"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be blank")
        return self


class IncidentUpdateInput(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    affected_component: str | None = Field(default=None, min_length=1, max_length=100)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=4000)
    observed_evidence: dict[str, Any] | None = None
    priority: str | None = Field(default=None, max_length=40)
    investigation_status: IncidentStatus | None = None

    @field_validator("observed_evidence")
    @classmethod
    def validate_evidence(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if value is None else _validate_observed_evidence(value)

    @model_validator(mode="after")
    def validate_update(self) -> "IncidentUpdateInput":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for name in ("title", "affected_component", "category", "observed_evidence", "investigation_status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        for name in ("title", "affected_component", "category"):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(f"{name} must not be blank")
        return self


class IncidentResponse(StrictModel):
    id: str
    simulation_run_id: str | None
    title: str
    affected_component: str
    category: str
    description: str | None
    observed_evidence: dict[str, Any]
    priority: str | None
    investigation_status: IncidentStatus
    created_at: str
    updated_at: str


class IncidentListResponse(StrictModel):
    items: list[IncidentResponse]
    page: int
    page_size: int
    total: int


class AnalysisFinding(StrictModel):
    component: str = Field(min_length=1, max_length=100)
    finding: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(min_length=1, max_length=100)


class AIAnalysisOutput(StrictModel):
    schema_version: Literal["1"]
    summary: str = Field(min_length=1, max_length=4000)
    findings: list[AnalysisFinding] = Field(max_length=100)

    @model_validator(mode="after")
    def validate_references_and_components(self) -> "AIAnalysisOutput":
        known_components = set(build_topology().nodes)
        for finding in self.findings:
            if finding.component not in known_components:
                raise ValueError("finding references an unknown component")
            forbidden_reference_terms = (
                "ground_truth", "fault_scenario", "fault_schedule",
                "fault_type", "fault_mode", "fault_severity",
            )
            if any(
                term in ref.lower()
                for ref in finding.evidence_refs
                for term in forbidden_reference_terms
            ):
                raise ValueError("AI evidence references cannot point to scenario ground truth")
        return self


class AnalysisSubmissionInput(StrictModel):
    start_tick: StrictInt = Field(default=0, ge=0)
    end_tick: StrictInt | None = Field(default=None, ge=0)


class AnalysisJobResponse(StrictModel):
    analysis_id: str
    status: Literal["pending", "running", "completed", "failed"]
    status_path: str


class AnalysisResultResponse(StrictModel):
    analysis_id: str
    simulation_run_id: str | None
    incident_id: str | None
    status: Literal["pending", "running", "completed", "failed"]
    provider_name: str | None
    model_name: str | None
    model_version: str | None
    schema_version: str
    result: AIAnalysisOutput | None
    failure_code: str | None
    failure_message: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None

