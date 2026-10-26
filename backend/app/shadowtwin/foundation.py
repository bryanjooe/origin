"""In-memory checkpoints of the existing simulator, separate from evidence.

Checkpoints privately contain schedules for faithful reproduction. Only projected
observable rows may enter ComparisonFrame; checkpoints are not inference input.
Capture a live runtime through its lock-protected shadow_snapshot() method.
"""
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
import math

from app.simulator import MicrogridSimulator
from app.sustainability import EnergyLedger


MAX_TICKS = 10000
MAX_ADVANCE_TICKS = 1000

# Existing telemetry names, not scenario metadata. Nested records are projected
# separately so an added label cannot leak through an otherwise permitted field.
_NUMERIC = (
    "tick", "elapsed_seconds", "hour", "irradiance", "expected_solar_kw",
    "actual_solar_kw", "solar_voltage_v", "solar_current_a", "measured_solar_kw",
    "measured_soc_pct", "measured_solar_voltage_v", "measured_solar_current_a",
    "battery_soc_pct", "battery_energy_kwh", "battery_power_kw", "battery_delta_kwh",
    "battery_loss_kwh", "demand_kw", "delivered_kw", "unmet_demand_kw",
    "controller_command_kw", "nominal_command_kw", "applied_reserve_soc_pct",
    "applied_discharge_limit_kw", "inverter_requested_kw", "inverter_actual_kw",
    "inverter_loss_kw", "curtailed_dc_kw", "excess_ac_kw", "message_source_tick",
    "message_age_seconds", "communication_latency_seconds", "redundant_solar_kw",
    "redundant_soc_pct",
)
_BOOLEANS = ("config_integrity_ok", "packet_dropped", "telemetry_available")
_PACKET_NUMERIC = ("source_tick", "solar_kw", "soc_pct", "demand_kw", "sequence_number")
_SECURITY_NUMERIC = (
    "message_sequence_number", "interarrival_seconds", "interarrival_mean_seconds",
    "redundant_solar_kw", "solar_disagreement_kw", "redundant_soc_pct", "soc_disagreement_pct",
)
_SECURITY_BOOLEANS = (
    "duplicate_sequence", "out_of_order_sequence", "config_integrity_match",
    "command_policy_consistent", "solar_sensors_agree", "battery_sensors_agree",
)


def _fields(row, numeric=(), booleans=()):
    result = {}
    for key in numeric:
        if key in row:
            value = row[key]
            if value is not None and (type(value) not in (float, int) or not math.isfinite(value)):
                raise ValueError(f"{key} must be finite numeric telemetry or None")
            result[key] = value
    for key in booleans:
        if key in row:
            if type(row[key]) is not bool:
                raise ValueError(f"{key} must be boolean telemetry")
            result[key] = row[key]
    if "auth_tag_validity" in row:
        if row["auth_tag_validity"] not in ("valid", "invalid", "missing"):
            raise ValueError("Unsupported authentication observation")
        result["auth_tag_validity"] = row["auth_tag_validity"]
    for key in ("config_hash", "last_known_good_config_hash"):
        if key in row:
            value = row[key]
            if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{key} must be a recorded SHA256 observation")
            result[key] = value
    return result


def _observable(row):
    result = _fields(row, _NUMERIC, _BOOLEANS)
    if type(result.get("tick")) is not int or result["tick"] < 0:
        raise ValueError("Comparison rows require a nonnegative integer tick")
    if result.get("elapsed_seconds") is None:
        raise ValueError("Comparison rows require elapsed_seconds")
    if "controller_rule" in row:
        if row["controller_rule"] not in ("await_telemetry", "renewable_first"):
            raise ValueError("Unsupported controller rule observation")
        result["controller_rule"] = row["controller_rule"]
    for key, numbers, booleans in (("controller_inputs", _PACKET_NUMERIC, ()),
                                  ("security_telemetry", _SECURITY_NUMERIC, _SECURITY_BOOLEANS)):
        if key in row:
            if row[key] is None:
                result[key] = None
            elif isinstance(row[key], Mapping):
                result[key] = _fields(row[key], numbers, booleans)
            else:
                raise ValueError(f"{key} must be a telemetry mapping or None")
    # This islanded simulator has no grid import/export model. None means
    # unavailable, never zero or an invented energy calculation.
    result.update(grid_import_kw=None, grid_export_kw=None)
    return result


@dataclass(frozen=True)
class ComparisonFrame:
    """Detached observations at one matching tick; no scores or conclusions."""
    experiment_id: str
    tick: int
    telemetry: dict[str, dict]

    @property
    def branch_ids(self):
        return tuple(self.telemetry)

    def __post_init__(self):
        if not isinstance(self.experiment_id, str) or not self.experiment_id.strip():
            raise ValueError("experiment_id must be a nonempty string")
        rows = self.telemetry
        if len(rows) < 2 or any(not isinstance(key, str) or not key.strip() for key in rows):
            raise ValueError("At least two named branches are required")
        observations = {key: _observable(rows[key]) for key in sorted(rows)}
        clocks = {(row["tick"], row["elapsed_seconds"]) for row in observations.values()}
        if len(clocks) != 1 or type(self.tick) is not int or next(iter(clocks))[0] != self.tick:
            raise ValueError("Comparison rows must have matching ticks and elapsed times")
        object.__setattr__(self, "telemetry", observations)

    @classmethod
    def from_rows(cls, experiment_id: str, rows: Mapping[str, dict]):
        if not rows:
            raise ValueError("At least two named branches are required")
        return cls(experiment_id, next(iter(rows.values())).get("tick"), rows)


class SimulationSnapshot:
    """An independent current-state checkpoint, not a seed-only reconstruction.

    The checkpoint's next_tick is its state boundary: at next_tick=100, ticks
    0..99 have run and the next generated observation is tick 100. Historical
    time travel is intentionally unsupported; capture at the desired boundary.
    """
    def __init__(self, simulator: MicrogridSimulator, *, ledger: EnergyLedger | None = None,
                 max_tick: int = MAX_TICKS, at_tick: int | None = None):
        if type(max_tick) is not int or not 1 <= max_tick <= MAX_TICKS:
            raise ValueError(f"max_tick must be an integer from 1 to {MAX_TICKS}")
        if type(simulator.tick) is not int or not 0 <= simulator.tick <= max_tick:
            raise ValueError("Simulator state is outside the experiment tick limit")
        if at_tick is not None and (type(at_tick) is not int or at_tick != simulator.tick):
            raise ValueError(f"Only the current state can be captured: requested {at_tick}, current {simulator.tick}")
        # Copy the object graph together, preserving aliases such as _last_fault
        # and the active scheduled fault while detaching every mutable object.
        self._simulator, self._ledger = deepcopy((simulator, ledger))
        if self._ledger is None:
            if len(simulator.history) != simulator.tick:
                raise ValueError("A complete telemetry history or matching energy ledger is required")
            self._ledger = EnergyLedger(self._simulator.config)
            for tick, row in enumerate(self._simulator.history):
                if row["tick"] != tick:
                    raise ValueError("Cannot reconstruct energy accounting from nonconsecutive history")
                self._ledger.update(row)
        if (self._ledger.ticks != self._simulator.tick or self._ledger.config != self._simulator.config
                or not math.isclose(self._ledger.energy, self._simulator.battery_kwh, rel_tol=0, abs_tol=1e-8)):
            raise ValueError("Energy ledger must match the captured simulator state")
        self._max_tick = max_tick

    @property
    def next_tick(self):
        return self._simulator.tick

    def fork(self, branch_id: str):
        return ShadowBranch(self, branch_id)


class ShadowBranch:
    """A bounded branch with no runtime, database, detector or incident writer."""
    def __init__(self, snapshot: SimulationSnapshot, branch_id: str):
        if not isinstance(branch_id, str) or not branch_id.strip():
            raise ValueError("branch_id must be a nonempty string")
        self.branch_id = branch_id
        self._simulator, self._ledger = deepcopy((snapshot._simulator, snapshot._ledger))
        self._max_tick = snapshot._max_tick

    @property
    def next_tick(self):
        return self._simulator.tick

    def advance(self, ticks: int, *, use_redundant_solar=False, restore_controller_policy=False):
        if type(ticks) is not int or not 0 <= ticks <= MAX_ADVANCE_TICKS:
            raise ValueError(f"Advance must be an integer from 0 to {MAX_ADVANCE_TICKS} ticks")
        if self.next_tick + ticks > self._max_tick:
            raise ValueError("Experiment would exceed its captured run tick limit")
        if type(use_redundant_solar) is not bool or type(restore_controller_policy) is not bool:
            raise ValueError("Experimental input choices must be boolean")
        rows = []
        for _ in range(ticks):
            row = self._simulator.step(use_redundant_solar=use_redundant_solar,
                                       restore_controller_policy=restore_controller_policy)
            self._ledger.update(row)
            rows.append(_observable(row))
        return rows

    def energy_snapshot(self):
        return self._ledger.snapshot()
