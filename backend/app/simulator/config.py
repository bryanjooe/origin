from dataclasses import dataclass, fields
from math import isfinite


@dataclass(frozen=True)
class GridConfig:
    tick_seconds: float = 60.0
    start_hour: float = 10.0
    solar_capacity_kw: float = 12.0
    dc_voltage_v: float = 400.0
    battery_capacity_kwh: float = 24.0
    initial_soc_pct: float = 60.0
    reserve_soc_pct: float = 10.0
    charge_limit_kw: float = 5.0
    discharge_limit_kw: float = 5.0
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    inverter_efficiency: float = 0.96
    inverter_limit_kw: float = 15.0
    base_demand_kw: float = 7.0
    communication_delay_ticks: int = 0
    packet_loss_probability: float = 0.0

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if not isinstance(value, (int, float)) or not isfinite(value):
                raise ValueError(f"{field.name} must be finite")
        for name in ("tick_seconds", "solar_capacity_kw", "dc_voltage_v",
                     "battery_capacity_kwh", "inverter_limit_kw", "base_demand_kw"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("charge_limit_kw", "discharge_limit_kw"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        for name in ("charge_efficiency", "discharge_efficiency", "inverter_efficiency"):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        if not 0 <= self.reserve_soc_pct <= self.initial_soc_pct <= 100:
            raise ValueError("Require 0 <= reserve <= initial SOC <= 100")
        if not 0 <= self.start_hour < 24:
            raise ValueError("start_hour must be in [0, 24)")
        if type(self.communication_delay_ticks) is not int or self.communication_delay_ticks < 0:
            raise ValueError("communication_delay_ticks must be a nonnegative integer")
        if not 0 <= self.packet_loss_probability <= 1:
            raise ValueError("packet_loss_probability must be in [0, 1]")
