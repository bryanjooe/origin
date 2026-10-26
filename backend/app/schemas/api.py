from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.fault_injection import Fault, FaultKind
from app.simulator import GridConfig


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GridSettings(RequestModel):
    tick_seconds: float = Field(60, ge=1, le=3600)
    start_hour: float = Field(10, ge=0, lt=24)
    solar_capacity_kw: float = Field(12, gt=0, le=1000)
    dc_voltage_v: float = Field(400, gt=0, le=2000)
    battery_capacity_kwh: float = Field(24, gt=0, le=10000)
    initial_soc_pct: float = Field(60, ge=0, le=100)
    reserve_soc_pct: float = Field(10, ge=0, le=100)
    charge_limit_kw: float = Field(5, ge=0, le=1000)
    discharge_limit_kw: float = Field(5, ge=0, le=1000)
    charge_efficiency: float = Field(0.95, gt=0, le=1)
    discharge_efficiency: float = Field(0.95, gt=0, le=1)
    inverter_efficiency: float = Field(0.96, gt=0, le=1)
    inverter_limit_kw: float = Field(15, gt=0, le=1000)
    base_demand_kw: float = Field(7, gt=0, le=1000)
    communication_delay_ticks: int = Field(0, ge=0, le=100, strict=True)
    packet_loss_probability: float = Field(0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_physics(self):
        self.grid_config()
        return self

    def grid_config(self):
        return GridConfig(**self.model_dump())


class FaultRequest(RequestModel):
    kind: FaultKind
    mode: str
    severity: float = Field(0.7, gt=0, le=1)
    duration_ticks: int = Field(30, ge=1, le=10000, strict=True)
    start_tick: int | None = Field(None, ge=0, le=10000, strict=True)

    @model_validator(mode="after")
    def validate_mode(self):
        self.fault(self.start_tick or 0)
        return self

    def fault(self, current_tick):
        return Fault(self.kind, self.mode, current_tick if self.start_tick is None else self.start_tick,
                     self.duration_ticks, self.severity)


class ScenarioRequest(RequestModel):
    seed: int = Field(42, ge=0, le=2147483647, strict=True)
    config: GridSettings = Field(default_factory=GridSettings)
    fault: FaultRequest | None = None


class ResetRequest(RequestModel):
    seed: int | None = Field(None, ge=0, le=2147483647, strict=True)


class StartRequest(RequestModel):
    speed: float | None = Field(None, ge=0.1, le=30)


class SpeedRequest(RequestModel):
    speed: float = Field(2, ge=0.1, le=30)


class StepRequest(RequestModel):
    ticks: int = Field(1, ge=1, le=300, strict=True)


class EvaluateRequest(RequestModel):
    profile: Literal["quick", "full"] = "full"


class Envelope(BaseModel):
    data: Any


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict] = Field(default_factory=list)


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
