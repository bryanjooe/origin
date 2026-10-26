from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.attack_injection import Attack, AttackType, StealthLevel
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


class AttackRequest(RequestModel):
    attack_type: AttackType
    target_component: str
    severity: float = Field(0.7, gt=0, le=1)
    duration_ticks: int = Field(30, ge=1, le=10000, strict=True)
    start_tick: int | None = Field(None, ge=0, le=10000, strict=True)
    stealth_level: StealthLevel = StealthLevel.MODERATE

    @model_validator(mode="after")
    def validate_attack(self):
        self.attack(self.start_tick or 0)
        return self

    def attack(self, current_tick):
        return Attack(self.attack_type, self.target_component,
                      current_tick if self.start_tick is None else self.start_tick,
                      self.duration_ticks, self.severity, self.stealth_level)


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


class ShadowHypothesisRequest(RequestModel):
    hypothesis_id: str = Field(min_length=1, max_length=64)
    component: Literal["solar_sensor", "controller", "communication"]
    mechanism: str = Field(min_length=1, max_length=160)
    intervention: Literal["use_redundant_solar", "restore_controller_policy", "flush_communication"]

    @model_validator(mode="after")
    def supported_pair(self):
        from app.shadowtwin.experiments import SUPPORTED_INTERVENTIONS
        if not self.hypothesis_id.strip() or not self.mechanism.strip():
            raise ValueError("Hypothesis ID and mechanism must not be blank")
        if SUPPORTED_INTERVENTIONS[self.intervention] != self.component:
            raise ValueError("The intervention does not support the selected component")
        return self


class ShadowCompareRequest(RequestModel):
    hypotheses: list[ShadowHypothesisRequest] = Field(min_length=2, max_length=6)
    duration_ticks: int = Field(20, ge=1, le=1000, strict=True)
    incident_id: str | None = Field(None, min_length=1, max_length=128)
    expected_run_id: str | None = Field(None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def bounded_batch(self):
        from app.shadowtwin.comparison import MAX_BRANCH_TICKS
        if len(self.hypotheses) * self.duration_ticks * 2 > MAX_BRANCH_TICKS:
            raise ValueError("ShadowTwin comparison exceeds the 480 branch-tick budget")
        if len({h.hypothesis_id for h in self.hypotheses}) != len(self.hypotheses):
            raise ValueError("Hypothesis identifiers must be unique")
        if len({(h.component, h.intervention, h.mechanism) for h in self.hypotheses}) != len(self.hypotheses):
            raise ValueError("Duplicate hypotheses require meaningfully different mechanisms")
        return self


class Envelope(BaseModel):
    data: Any


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict] = Field(default_factory=list)


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
