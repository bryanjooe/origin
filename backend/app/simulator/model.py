"""Discrete-time power balance. Positive battery power means discharge."""
from collections import deque
from dataclasses import asdict
import math
import random

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
        self.tick = 0
        self.battery_kwh = self.config.battery_capacity_kwh * self.config.initial_soc_pct / 100
        self._cloud = 0.9
        self._pending = deque()
        self._latest = None
        self._stuck = None
        self._previous_request = 0.0
        self._last_fault = None
        self.history: list[dict] = []
        self.events: list[dict] = []
        self.faults.clear()

    def inject(self, kind: FaultKind | str, mode: str, severity=0.7,
               duration_ticks=30, start_tick: int | None = None):
        fault = Fault(kind, mode, self.tick if start_tick is None else start_tick,
                      duration_ticks, severity)
        self.faults.schedule(fault, self.tick)
        return fault

    def correct(self):
        """Restore simulated components and flush corrupted/stale queued messages."""
        self.faults.cancel_all(self.tick)
        self._pending.clear()
        self._latest = None
        self._stuck = None
        self.events.append({"tick": self.tick, "event": "simulated_correction"})

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
        packet = {"source_tick": tick, "solar_kw": measured,
                  "soc_pct": measured_soc, "demand_kw": demand}
        delay = c.communication_delay_ticks
        dropped = self._communication.random() < c.packet_loss_probability
        if fault and fault.kind == FaultKind.COMMUNICATION:
            if fault.mode == "delay":
                delay += max(1, math.ceil(8 * severity))
            elif fault.mode in ("drop", "stale"):
                dropped = fault.mode == "stale" or self._communication.random() < severity
            elif fault.mode == "corrupt":
                packet["solar_kw"] += 2 * c.solar_capacity_kw * severity
        if not dropped:
            self._pending.append((tick + delay, packet))
        remaining = deque()
        while self._pending:
            due, message = self._pending.popleft()
            if due <= tick:
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
            requested = min(inputs["demand_kw"], c.inverter_limit_kw,
                            max(0, inputs["solar_kw"] + command) * c.inverter_efficiency)
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
        self._previous_request = requested
        inverter = min(target, available_dc * efficiency, limit)
        dc_used = inverter / efficiency
        inverter_loss = dc_used - inverter
        curtailed = max(0, available_dc - dc_used)
        delivered = min(inverter, demand)
        excess_ac = inverter - delivered
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
        }
        self.history.append(row)
        self.tick += 1
        return row

    def settings(self):
        return {"seed": self.seed, "config": asdict(self.config)}
