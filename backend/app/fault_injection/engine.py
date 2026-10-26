"""Hidden scenario truth; never merge these records into inference telemetry."""
from dataclasses import dataclass
from enum import Enum
from math import isfinite


class FaultKind(str, Enum):
    SENSOR = "sensor"
    COMMUNICATION = "communication"
    CONTROLLER = "controller"
    FIRMWARE = "firmware"
    INVERTER = "inverter"


MODES = {
    FaultKind.SENSOR: {"bias", "drift", "stuck", "noise", "soc_bias"},
    FaultKind.COMMUNICATION: {"delay", "drop", "stale", "corrupt"},
    FaultKind.CONTROLLER: {"wrong_dispatch"},
    FaultKind.FIRMWARE: {"discharge_limit", "reserve_threshold"},
    FaultKind.INVERTER: {"derate", "shutdown", "efficiency", "delay"},
}


@dataclass(frozen=True)
class Fault:
    kind: FaultKind
    mode: str
    start_tick: int
    duration_ticks: int = 30
    severity: float = 0.7

    def __post_init__(self):
        object.__setattr__(self, "kind", FaultKind(self.kind))
        if self.mode not in MODES[self.kind]:
            raise ValueError(f"Unsupported mode {self.mode!r} for {self.kind.value}")
        if type(self.start_tick) is not int or self.start_tick < 0:
            raise ValueError("start_tick must be a nonnegative integer")
        if type(self.duration_ticks) is not int or self.duration_ticks < 1:
            raise ValueError("duration_ticks must be a positive integer")
        if not isfinite(self.severity) or not 0 < self.severity <= 1:
            raise ValueError("severity must be in (0, 1]")

    def active(self, tick: int) -> bool:
        return self.start_tick <= tick < self.start_tick + self.duration_ticks


class FaultEngine:
    def __init__(self):
        self._schedule: list[Fault] = []
        self._records: list[dict] = []

    def schedule(self, fault: Fault, current_tick: int = 0):
        if fault.start_tick < current_tick:
            raise ValueError("Cannot schedule faults in the past")
        for existing in self._schedule:
            if max(existing.start_tick, fault.start_tick) < min(
                existing.start_tick + existing.duration_ticks,
                fault.start_tick + fault.duration_ticks,
            ):
                raise ValueError("Overlapping faults are not supported")
        self._schedule.append(fault)
        self._schedule.sort(key=lambda item: item.start_tick)
        self._records.append(dict(kind=fault.kind.value, mode=fault.mode,
                                  start_tick=fault.start_tick,
                                  duration_ticks=fault.duration_ticks,
                                  severity=fault.severity, cancelled_at_tick=None))

    def at(self, tick: int) -> Fault | None:
        return next((fault for fault in self._schedule if fault.active(tick)), None)

    def clear(self):
        self._schedule.clear()
        self._records.clear()

    def cancel_all(self, tick: int):
        for record in self._records:
            if record["start_tick"] + record["duration_ticks"] > tick and record["cancelled_at_tick"] is None:
                record["cancelled_at_tick"] = tick
        self._schedule.clear()

    def ground_truth(self) -> list[dict]:
        return [dict(record) for record in self._records]
