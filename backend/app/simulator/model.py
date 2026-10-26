"""Discrete-time power balance. Positive battery power means discharge."""
from collections import deque
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
import random

from app.attack_injection import Attack, AttackEngine, AttackType, StealthLevel
from app.fault_injection import Fault, FaultEngine, FaultKind
from .config import GridConfig


def clamp(value, low, high):
    return max(low, min(high, value))


class MicrogridSimulator:
    def __init__(self, config: GridConfig | None = None, seed: int = 42):
        self.config = config or GridConfig()
        self.seed = seed
        self.faults = FaultEngine()
        self.reset()

    def reset(self, seed: int | None = None):
        if seed is not None:
            self.seed = seed
        # Separate streams keep weather identical in paired baseline/fault runs.
        self._weather = random.Random(self.seed)
        self._measurement = random.Random(self.seed + 1)
        self._communication = random.Random(self.seed + 2)
        self._redundant_measurement = random.Random(self.seed + 3)
        self._attack_random = random.Random(self.seed + 4)
        # Independent seeded stream for packet integrity imperfections. Keeping
        # this separate avoids changing the simulator's communication schedule.
        self._security_random = random.Random(self.seed + 5)
        self.tick = 0
        self.battery_kwh = self.config.battery_capacity_kwh * self.config.initial_soc_pct / 100
        self._cloud = 0.9
        self._pending = deque()
        self._latest = None
        self._stuck = None
        self._previous_request = 0.0
        self._last_fault = None
        self.faults = FaultEngine()
        self.attacks = AttackEngine()
        self._message_sequence = 0
        self._last_sent_sequence = None
        self._last_received_sequence = None
        self._last_received_tick = None
        self._interarrival_history = deque(maxlen=8)
        self._stealth_config_visible_from = {}
        self.history: list[dict] = []
        self.events: list[dict] = []

    def inject(self, kind: FaultKind | str, mode: str, severity=0.7,
               duration_ticks=30, start_tick: int | None = None):
        fault = Fault(kind, mode, self.tick if start_tick is None else start_tick,
                      duration_ticks, severity)
        self.faults.schedule(fault, self.tick)
        return fault

    def inject_attack(self, attack_type: AttackType | str, target_component: str,
                      severity=0.7, duration_ticks=30, start_tick: int | None = None,
                      stealth_level: StealthLevel | str = StealthLevel.MODERATE):
        """Schedule an abstract in-memory attack; no network or device is contacted."""
        attack = Attack(AttackType(attack_type), target_component,
                        self.tick if start_tick is None else start_tick,
                        duration_ticks, severity, StealthLevel(stealth_level))
        self.attacks.schedule(attack, self.tick)
        return attack

    def correct(self):
        """Restore simulated components and flush corrupted/stale queued messages."""
        active_faults = [item for item in self.faults.ground_truth()
                         if item["cancelled_at_tick"] is None
                         and item["start_tick"] <= self.tick < item["start_tick"] + item["duration_ticks"]]
        active_attacks = [item for item in self.attacks.ground_truth()
                          if item["cancelled_at_tick"] is None
                          and item["start_tick"] <= self.tick < item["start_tick"] + item["duration_ticks"]]
        pending_messages = len(self._pending)
        stale_message_cleared = self._latest is not None or self._stuck is not None
        self.faults.cancel_all(self.tick)
        self.attacks.cancel_all(self.tick)
        self._pending.clear()
        self._latest = None
        self._stuck = None
        actions = []
        if active_faults:
            actions.append({"label": "Cancelled active simulated fault", "detail": f"{len(active_faults)} scheduled fault(s) stopped at tick {self.tick}."})
        if active_attacks:
            actions.append({"label": "Cancelled active simulated attack", "detail": f"{len(active_attacks)} scheduled attack(s) stopped at tick {self.tick}."})
        if pending_messages or stale_message_cleared:
            actions.append({"label": "Cleared stale communication state", "detail": f"{pending_messages} queued message(s) flushed; cached communication state reset."})
        if not actions:
            actions.append({"label": "Simulation state restored", "detail": "No active injected fault, attack, or stale communication state remained at the time of correction."})
        result = {"correction_tick": self.tick, "actions_applied": actions}
        self.events.append({"tick": self.tick, "event": "simulated_correction", **result})
        return result

    def run(self, ticks: int) -> list[dict]:
        if type(ticks) is not int or ticks < 0:
            raise ValueError("ticks must be a nonnegative integer")
        return [self.step() for _ in range(ticks)]

    def step(self) -> dict:
        c, tick = self.config, self.tick
        dt = c.tick_seconds / 3600
        elapsed = tick * c.tick_seconds
        hour = (c.start_hour + elapsed / 3600) % 24
        fault = self.faults.at(tick)
        attack = self.attacks.at(tick)
        attack_type, attack_target = self._attack_stage(attack, tick)
        is_multistage = attack is not None and attack.attack_type is AttackType.MULTI_STAGE
        attack_stage_index = attack.stage_index(tick) if is_multistage else 0
        if fault is not self._last_fault:
            self.events.append({"tick": tick, "event": "scenario_transition"})
            self._stuck = None
        self._last_fault = fault
        severity = fault.severity if fault else 0
        self._cloud = clamp(0.94 * self._cloud + 0.06 * self._weather.uniform(0.35, 1), 0.3, 1)
        daylight = max(0, math.sin(math.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0
        irradiance = daylight * self._cloud
        solar = c.solar_capacity_kw * irradiance
        demand = c.base_demand_kw * (0.8 + 0.3 * math.exp(-((hour - 19) / 3) ** 2)
                                    + 0.15 * math.exp(-((hour - 8) / 2) ** 2))
        demand *= self._weather.uniform(0.97, 1.03)
        initial_energy = self.battery_kwh
        soc = initial_energy / c.battery_capacity_kwh * 100
        measured = max(0, solar + self._measurement.gauss(0, 0.015 * solar))
        measured_soc = clamp(soc + self._measurement.gauss(0, 0.05), 0, 100)
        measured_demand = demand
        redundant_solar = max(0, solar + self._redundant_measurement.gauss(0, 0.015 * solar))
        redundant_soc = clamp(soc + self._redundant_measurement.gauss(0, 0.05), 0, 100)
        if fault and fault.kind == FaultKind.SENSOR:
            if fault.mode == "bias":
                measured += severity * c.solar_capacity_kw
            elif fault.mode == "drift":
                measured += severity * c.solar_capacity_kw * (tick - fault.start_tick + 1) / fault.duration_ticks
            elif fault.mode == "noise":
                measured = max(0, measured + self._measurement.gauss(0, severity * c.solar_capacity_kw))
            elif fault.mode == "soc_bias":
                measured_soc = clamp(measured_soc + 60 * severity, 0, 100)
            elif fault.mode == "stuck":
                if self._stuck is None:
                    self._stuck = self.history[-1]["measured_solar_kw"] if self.history else measured
                measured = self._stuck
        if attack_type is AttackType.SENSOR_SPOOF:
            progress = self._attack_progress(attack, tick)
            amount = attack.severity * progress
            stealth = attack.stealth_level
            if attack_target == "solar_sensor":
                # Gradual spoofing is bounded to a plausible fraction of rated output.
                fraction = {StealthLevel.NAIVE: 1.0, StealthLevel.MODERATE: 0.35,
                            StealthLevel.STEALTHY: 0.12}[stealth]
                measured = max(0.0, measured + c.solar_capacity_kw * amount * fraction)
            elif attack_target == "battery_sensor":
                offset = {StealthLevel.NAIVE: 60.0, StealthLevel.MODERATE: 18.0,
                          StealthLevel.STEALTHY: 6.0}[stealth]
                measured_soc = clamp(measured_soc + offset * amount, 0, 100)
            elif attack_target == "demand_sensor":
                fraction = {StealthLevel.NAIVE: 0.75, StealthLevel.MODERATE: 0.18,
                            StealthLevel.STEALTHY: 0.06}[stealth]
                measured_demand = demand * (1 + fraction * amount)
        # Authentication telemetry is intentionally imperfect in both
        # directions: ordinary links occasionally report a bad tag, and
        # compromised links can still produce a valid tag.
        auth_valid = self._security_random.random() >= 0.01
        packet = {"source_tick": tick, "solar_kw": measured,
                  "soc_pct": measured_soc, "demand_kw": measured_demand,
                  "sequence_number": self._message_sequence,
                  "auth_tag_validity": "valid" if auth_valid else "invalid"}
        self._message_sequence += 1
        delay = c.communication_delay_ticks
        dropped = self._communication.random() < c.packet_loss_probability
        if fault and fault.kind == FaultKind.COMMUNICATION:
            if fault.mode == "delay":
                delay += max(1, math.ceil(8 * severity))
            elif fault.mode in ("drop", "stale"):
                dropped = fault.mode == "stale" or self._communication.random() < severity
            elif fault.mode == "corrupt":
                packet["solar_kw"] += 2 * c.solar_capacity_kw * severity
        if attack_type is AttackType.REPLAY and self.history:
            # Replay frequency decreases with stealth but keeps sequence and
            # message-age evidence observable.
            interval = {StealthLevel.NAIVE: 1, StealthLevel.MODERATE: 2,
                        StealthLevel.STEALTHY: 5}[attack.stealth_level]
            if (tick - attack.start_tick) % interval == 0:
                previous = self.history[-1].get("controller_inputs")
                if previous is not None:
                    packet = deepcopy(previous)
        elif attack_type is AttackType.COMMUNICATION_DEGRADATION:
            strength = attack.severity * self._stealth_scale(attack)
            delay += max(1, math.ceil(4 * strength))
            if attack.stealth_level is StealthLevel.STEALTHY:
                if tick % 5 == attack.start_tick % 5 and self.history:
                    previous = self.history[-1].get("controller_inputs")
                    if previous is not None:
                        packet = deepcopy(previous)
            elif self._attack_random.random() < 0.2 * strength:
                dropped = True
        elif attack_type is AttackType.MESSAGE_TAMPERING and attack_target == "communication":
            packet["solar_kw"] = max(0.0, packet["solar_kw"] + c.solar_capacity_kw *
                                     attack.severity * 0.45 * self._stealth_scale(attack))
            invalid_probability = {StealthLevel.NAIVE: 0.9, StealthLevel.MODERATE: 0.7,
                                   StealthLevel.STEALTHY: 0.25}[attack.stealth_level]
            draw = self._security_random.random()
            packet["auth_tag_validity"] = (
                "invalid" if draw < invalid_probability else
                "missing" if attack.stealth_level is StealthLevel.STEALTHY and draw < 0.6 else "valid"
            )
        if is_multistage and attack_stage_index == 0:
            # The opening phase degrades communication and can replay a stale packet.
            delay += max(1, math.ceil(3 * attack.severity * self._stealth_scale(attack)))
            if tick % 3 == attack.start_tick % 3 and self.history:
                previous = self.history[-1].get("controller_inputs")
                if previous is not None:
                    packet = deepcopy(previous)
        sent_sequence = packet.get("sequence_number")
        duplicate_sequence = (self._last_sent_sequence is not None and
                              sent_sequence == self._last_sent_sequence)
        out_of_order_sequence = (self._last_sent_sequence is not None and
                                 isinstance(sent_sequence, int) and sent_sequence < self._last_sent_sequence)
        if isinstance(sent_sequence, int) and (self._last_sent_sequence is None or sent_sequence > self._last_sent_sequence):
            self._last_sent_sequence = sent_sequence
        if not dropped:
            self._pending.append((tick + delay, packet))
        remaining = deque()
        interarrival_seconds = None
        while self._pending:
            due, message = self._pending.popleft()
            if due <= tick:
                sequence = message.get("sequence_number")
                if isinstance(sequence, int):
                    if self._last_received_sequence is not None:
                        duplicate_sequence |= sequence == self._last_received_sequence
                        out_of_order_sequence |= sequence < self._last_received_sequence
                    if self._last_received_tick is not None:
                        interarrival_seconds = (tick - self._last_received_tick) * c.tick_seconds
                        self._interarrival_history.append(interarrival_seconds)
                    self._last_received_tick = tick
                    if self._last_received_sequence is None or sequence > self._last_received_sequence:
                        self._last_received_sequence = sequence
                if self._latest is None or message["source_tick"] > self._latest["source_tick"]:
                    self._latest = message
            else:
                remaining.append((due, message))
        self._pending = remaining
        inputs = dict(self._latest) if self._latest is not None else None
        reserve, discharge_limit = c.reserve_soc_pct, c.discharge_limit_kw
        integrity = True
        if fault and fault.kind == FaultKind.FIRMWARE:
            integrity = False
            if fault.mode == "discharge_limit":
                discharge_limit *= 1 - severity
            else:
                reserve = c.reserve_soc_pct + (100 - c.reserve_soc_pct) * severity
        if attack_type is AttackType.FIRMWARE_TAMPERING:
            if attack.target_component == "firmware":
                strength = attack.severity * self._stealth_scale(attack)
                reserve = min(100.0, c.reserve_soc_pct + strength * 55.0)
                discharge_limit *= 1 - 0.65 * strength
                detection_tick = self._stealth_config_visible_from.setdefault(
                    (attack.start_tick, attack.attack_type.value), attack.start_tick + 5
                ) if attack.stealth_level is StealthLevel.STEALTHY else tick
                if tick >= detection_tick:
                    integrity = False
        if inputs is None:
            nominal_command = command = 0.0
            requested = 0.0  # Fail safe until a timestamped measurement arrives.
            rule = "await_telemetry"
        else:
            deficit = inputs["demand_kw"] / c.inverter_efficiency - inputs["solar_kw"]
            nominal_command = clamp(deficit, -c.charge_limit_kw, discharge_limit)
            if nominal_command > 0 and inputs["soc_pct"] <= reserve:
                nominal_command = 0.0
            if nominal_command < 0 and inputs["soc_pct"] >= 100:
                nominal_command = 0.0
            command = nominal_command
            if fault and fault.kind == FaultKind.CONTROLLER:
                command = -c.charge_limit_kw * severity
            if attack_type is AttackType.CONTROLLER_COMPROMISE:
                strength = attack.severity * self._stealth_scale(attack)
                forced_drain = min(c.discharge_limit_kw, c.discharge_limit_kw * strength)
                # Prefer policy-violating discharge; when normal policy already
                # saturates at that limit, issue a conspicuously wrong charge command.
                command = (forced_drain if abs(forced_drain - nominal_command) > 0.1
                           else -c.charge_limit_kw * strength)
            elif attack_type is AttackType.MESSAGE_TAMPERING and attack_target == "controller":
                command = clamp(command + c.discharge_limit_kw * attack.severity * self._stealth_scale(attack),
                                -c.charge_limit_kw, c.discharge_limit_kw)
            requested = min(inputs["demand_kw"], c.inverter_limit_kw,
                            max(0, inputs["solar_kw"] + command) * c.inverter_efficiency)
            if attack_type is AttackType.MESSAGE_TAMPERING and attack_target == "inverter":
                requested *= 1 - 0.6 * attack.severity * self._stealth_scale(attack)
            rule = "renewable_first"
        # Independent physical protections remain in effect even under bad commands.
        minimum_energy = c.battery_capacity_kwh * c.reserve_soc_pct / 100
        if command >= 0:
            battery_power = min(command, c.discharge_limit_kw,
                                max(0, initial_energy - minimum_energy) * c.discharge_efficiency / dt)
            self.battery_kwh -= battery_power * dt / c.discharge_efficiency
            battery_loss = battery_power * dt * (1 / c.discharge_efficiency - 1)
        else:
            charge = min(-command, c.charge_limit_kw, solar,
                         (c.battery_capacity_kwh - initial_energy) / (c.charge_efficiency * dt))
            battery_power = -charge
            self.battery_kwh += charge * c.charge_efficiency * dt
            battery_loss = charge * dt * (1 - c.charge_efficiency)
        available_dc = max(0, solar + battery_power)
        efficiency, limit, target = c.inverter_efficiency, c.inverter_limit_kw, requested
        if fault and fault.kind == FaultKind.INVERTER:
            if fault.mode == "derate":
                target *= 1 - severity
            elif fault.mode == "shutdown":
                target = 0.0
            elif fault.mode == "efficiency":
                efficiency *= 1 - 0.8 * severity
            else:
                target = (1 - severity) * requested + severity * self._previous_request
        if attack_type is AttackType.ACTUATOR_ABUSE:
            target *= 1 - attack.severity * self._stealth_scale(attack)
        self._previous_request = requested
        inverter = min(target, available_dc * efficiency, limit)
        dc_used = inverter / efficiency
        inverter_loss = dc_used - inverter
        curtailed = max(0, available_dc - dc_used)
        delivered = min(inverter, demand)
        excess_ac = inverter - delivered
        actual_config = asdict(c)
        actual_config["reserve_soc_pct"] = reserve
        actual_config["discharge_limit_kw"] = discharge_limit
        last_known_good_hash = self._config_hash(asdict(c))
        actual_config_hash = self._config_hash(actual_config)
        if attack_type is AttackType.FIRMWARE_TAMPERING and attack is not None and integrity:
            reported_config_hash = last_known_good_hash
        else:
            reported_config_hash = actual_config_hash
        config_integrity_match = reported_config_hash == last_known_good_hash
        interarrival_mean = (sum(self._interarrival_history) / len(self._interarrival_history)
                             if self._interarrival_history else None)
        solar_disagreement = abs(measured - redundant_solar)
        soc_disagreement = abs(measured_soc - redundant_soc)
        command_consistent = abs(command - nominal_command) <= 0.1
        security_telemetry = {
            "message_sequence_number": (inputs.get("sequence_number") if inputs else None),
            "auth_tag_validity": (inputs.get("auth_tag_validity", "missing") if inputs else "missing"),
            "interarrival_seconds": interarrival_seconds,
            "interarrival_mean_seconds": interarrival_mean,
            "duplicate_sequence": duplicate_sequence,
            "out_of_order_sequence": out_of_order_sequence,
            "config_hash": reported_config_hash,
            "last_known_good_config_hash": last_known_good_hash,
            "config_integrity_match": config_integrity_match,
            "command_policy_consistent": command_consistent,
            "redundant_solar_kw": redundant_solar,
            "solar_disagreement_kw": solar_disagreement,
            "solar_sensors_agree": solar_disagreement <= max(0.08, 0.025 * c.solar_capacity_kw),
            "redundant_soc_pct": redundant_soc,
            "soc_disagreement_pct": soc_disagreement,
            "battery_sensors_agree": soc_disagreement <= 0.15,
        }
        row = {
            "tick": tick, "elapsed_seconds": elapsed, "hour": hour,
            "irradiance": irradiance, "expected_solar_kw": solar, "actual_solar_kw": solar,
            "solar_voltage_v": c.dc_voltage_v if solar > 0 else 0.0,
            "solar_current_a": solar * 1000 / c.dc_voltage_v,
            "measured_solar_kw": measured, "measured_soc_pct": measured_soc,
            "measured_solar_voltage_v": c.dc_voltage_v if measured > 0 else 0.0,
            "measured_solar_current_a": measured * 1000 / c.dc_voltage_v,
            "battery_soc_pct": self.battery_kwh / c.battery_capacity_kwh * 100,
            "battery_energy_kwh": self.battery_kwh, "battery_power_kw": battery_power,
            "battery_delta_kwh": self.battery_kwh - initial_energy,
            "battery_loss_kwh": battery_loss, "demand_kw": demand,
            "delivered_kw": delivered, "unmet_demand_kw": max(0, demand - delivered),
            "controller_inputs": inputs, "controller_rule": rule,
            "controller_command_kw": command, "nominal_command_kw": nominal_command,
            "applied_reserve_soc_pct": reserve, "applied_discharge_limit_kw": discharge_limit,
            "config_integrity_ok": integrity, "inverter_requested_kw": requested,
            "inverter_actual_kw": inverter, "inverter_loss_kw": inverter_loss,
            "curtailed_dc_kw": curtailed, "excess_ac_kw": excess_ac,
            "message_source_tick": inputs["source_tick"] if inputs else None,
            "message_age_seconds": (tick - inputs["source_tick"]) * c.tick_seconds if inputs else None,
            "communication_latency_seconds": delay * c.tick_seconds,
            "packet_dropped": dropped, "telemetry_available": inputs is not None,
            "redundant_solar_kw": redundant_solar,
            "redundant_soc_pct": redundant_soc,
            "security_telemetry": security_telemetry,
        }
        self.history.append(row)
        self.tick += 1
        return row

    def settings(self):
        return {"seed": self.seed, "config": asdict(self.config)}

    @staticmethod
    def _config_hash(values: dict) -> str:
        payload = json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _attack_progress(attack: Attack | None, tick: int) -> float:
        if attack is None or attack.stealth_level is not StealthLevel.STEALTHY:
            return 1.0
        return min(1.0, max(1.0 / attack.duration_ticks,
                            (tick - attack.start_tick + 1) / attack.duration_ticks))

    @staticmethod
    def _stealth_scale(attack: Attack | None) -> float:
        if attack is None:
            return 1.0
        return {StealthLevel.NAIVE: 1.0, StealthLevel.MODERATE: 0.65,
                StealthLevel.STEALTHY: 0.35}[attack.stealth_level]

    @staticmethod
    def _attack_stage(attack: Attack | None, tick: int) -> tuple[AttackType | None, str | None]:
        if attack is None:
            return None, None
        if attack.attack_type is not AttackType.MULTI_STAGE:
            return attack.attack_type, attack.target_component
        phase_targets = (
            (AttackType.COMMUNICATION_DEGRADATION, "communication"),
            (AttackType.SENSOR_SPOOF, "solar_sensor"),
            (AttackType.CONTROLLER_COMPROMISE, "controller"),
            (AttackType.ACTUATOR_ABUSE, "inverter"),
        )
        return phase_targets[attack.stage_index(tick)]
