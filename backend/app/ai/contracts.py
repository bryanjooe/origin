"""Versioned, prediction-time-only payload contracts for the separate AI component."""
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas import AIAnalysisOutput, ControllerInputs


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AnalysisWindow(StrictContract):
    start_tick: int = Field(ge=0)
    end_tick: int = Field(gt=0, description="Exclusive end tick; telemetry at this tick is not included")

    @model_validator(mode="after")
    def check_nonempty(self) -> "AnalysisWindow":
        if self.start_tick >= self.end_tick:
            raise ValueError("analysis window must contain at least one tick")
        return self


class InferenceTelemetryRow(StrictContract):
    """Observed channels only; deliberately omits simulator oracle/state fields."""

    tick: int
    elapsed_seconds: float
    hour: float
    measured_solar_kw: float
    measured_soc_pct: float
    measured_solar_voltage_v: float
    measured_solar_current_a: float
    demand_kw: float
    delivered_kw: float
    unmet_demand_kw: float


class InferenceControllerLog(StrictContract):
    """Controller-visible inputs/commands without the simulated integrity oracle."""

    tick: int
    elapsed_seconds: float
    controller_inputs: ControllerInputs | None
    controller_rule: str
    controller_command_kw: float
    nominal_command_kw: float
    applied_reserve_soc_pct: float
    applied_discharge_limit_kw: float
    inverter_requested_kw: float
    inverter_actual_kw: float
    message_source_tick: int | None
    message_age_seconds: float | None
    communication_latency_seconds: float
    packet_dropped: bool
    telemetry_available: bool


class AnalysisInferenceRequest(StrictContract):
    """Only observations available by the requested window's exclusive end."""

    schema_version: Literal["1"] = "1"
    analysis_id: str
    simulation_run_id: str
    window: AnalysisWindow
    telemetry: list[InferenceTelemetryRow]
    controller_logs: list[InferenceControllerLog]

    @model_validator(mode="after")
    def validate_observation_window(self) -> "AnalysisInferenceRequest":
        expected_ticks = list(range(self.window.start_tick, self.window.end_tick))
        telemetry_ticks = [row.tick for row in self.telemetry]
        log_ticks = [row.tick for row in self.controller_logs]
        if telemetry_ticks != expected_ticks or log_ticks != expected_ticks:
            raise ValueError("telemetry and controller logs must exactly cover the requested tick window")
        return self


class ProviderAnalysisResponse(StrictContract):
    """Provider response envelope. `result` is validated again before persistence."""

    model_name: str | None = Field(default=None, max_length=120)
    model_version: str | None = Field(default=None, max_length=120)
    result: AIAnalysisOutput


class AnalysisProvider(Protocol):
    """Adapters implement one bounded request; callers own job and persistence state."""

    def analyze(self, request: AnalysisInferenceRequest) -> ProviderAnalysisResponse:
        ...
