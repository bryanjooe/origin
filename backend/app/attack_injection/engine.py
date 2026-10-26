"""Abstract, in-memory cyber-attack schedules for the microgrid simulator.

Attack records are scenario ground truth. They must not be copied into telemetry
or passed to feature extractors.
"""
from dataclasses import dataclass
from enum import Enum
from math import isfinite


class AttackType(str, Enum):
    SENSOR_SPOOF = "sensor_spoof"
    REPLAY = "replay"
    COMMUNICATION_DEGRADATION = "communication_degradation"
    MESSAGE_TAMPERING = "message_tampering"
    CONTROLLER_COMPROMISE = "controller_compromise"
    FIRMWARE_TAMPERING = "firmware_tampering"
    ACTUATOR_ABUSE = "actuator_abuse"
    MULTI_STAGE = "multi_stage"


class StealthLevel(str, Enum):
    NAIVE = "naive"
    MODERATE = "moderate"
    STEALTHY = "stealthy"


COMPONENTS = frozenset({
    "solar_sensor", "battery_sensor", "demand_sensor", "communication",
    "controller", "firmware", "inverter",
})


@dataclass(frozen=True)
class Attack:
    attack_type: AttackType
    target_component: str
    start_tick: int
    duration_ticks: int = 30
    severity: float = 0.7
    stealth_level: StealthLevel = StealthLevel.MODERATE

    def __post_init__(self):
        object.__setattr__(self, "attack_type", AttackType(self.attack_type))
        object.__setattr__(self, "stealth_level", StealthLevel(self.stealth_level))
        if self.target_component not in COMPONENTS:
            raise ValueError(f"Unsupported attack target {self.target_component!r}")
        if type(self.start_tick) is not int or self.start_tick < 0:
            raise ValueError("start_tick must be a nonnegative integer")
        if type(self.duration_ticks) is not int or self.duration_ticks < 1:
            raise ValueError("duration_ticks must be a positive integer")
        if not isfinite(self.severity) or not 0 < self.severity <= 1:
            raise ValueError("severity must be in (0, 1]")
        compatible = {
            AttackType.SENSOR_SPOOF: {"solar_sensor", "battery_sensor", "demand_sensor"},
            AttackType.REPLAY: {"communication"},
            AttackType.COMMUNICATION_DEGRADATION: {"communication"},
            AttackType.MESSAGE_TAMPERING: {"communication", "controller", "inverter"},
            AttackType.CONTROLLER_COMPROMISE: {"controller"},
            AttackType.FIRMWARE_TAMPERING: {"firmware"},
            AttackType.ACTUATOR_ABUSE: {"inverter"},
            AttackType.MULTI_STAGE: COMPONENTS,
        }
        if self.target_component not in compatible[self.attack_type]:
            raise ValueError(f"Target {self.target_component!r} is not valid for {self.attack_type.value}")

    def active(self, tick: int) -> bool:
        return self.start_tick <= tick < self.start_tick + self.duration_ticks

    def stage_index(self, tick: int) -> int:
        """Return an internal multi-stage phase index; never include it in telemetry."""
        if self.attack_type is not AttackType.MULTI_STAGE:
            return 0
        elapsed = max(0, tick - self.start_tick)
        phase_length = max(1, self.duration_ticks // 4)
        return min(3, elapsed // phase_length)


class AttackEngine:
    """Deterministic schedule and ground-truth store, separate from observations."""

    def __init__(self):
        self._schedule: list[Attack] = []
        self._records: list[dict] = []

    def schedule(self, attack: Attack, current_tick: int = 0):
        if not isinstance(attack, Attack):
            raise TypeError("attack must be an Attack")
        if attack.start_tick < current_tick:
            raise ValueError("Cannot schedule attacks in the past")
        for existing in self._schedule:
            if max(existing.start_tick, attack.start_tick) < min(
                existing.start_tick + existing.duration_ticks,
                attack.start_tick + attack.duration_ticks,
            ):
                raise ValueError("Overlapping attacks are not supported")
        self._schedule.append(attack)
        self._schedule.sort(key=lambda item: item.start_tick)
        self._records.append({
            "attack_type": attack.attack_type.value,
            "target_component": attack.target_component,
            "severity": attack.severity,
            "start_tick": attack.start_tick,
            "duration_ticks": attack.duration_ticks,
            "stealth_level": attack.stealth_level.value,
            "cancelled_at_tick": None,
        })

    def at(self, tick: int) -> Attack | None:
        return next((attack for attack in self._schedule if attack.active(tick)), None)

    def clear(self):
        self._schedule.clear()
        self._records.clear()

    def cancel_all(self, tick: int):
        for record in self._records:
            if record["start_tick"] + record["duration_ticks"] > tick and record["cancelled_at_tick"] is None:
                record["cancelled_at_tick"] = tick
        self._schedule.clear()

    def ground_truth(self) -> list[dict]:
        """Return scenario labels for test/evaluation code, not inference inputs."""
        return [dict(record) for record in self._records]
