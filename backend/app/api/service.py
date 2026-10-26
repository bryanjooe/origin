"""Synchronized application services over the existing simulator modules."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import StringIO
import json
import threading
from uuid import uuid4

from app.fault_injection import FaultKind
from app.fault_injection.engine import MODES
from app.simulator import GridConfig, MicrogridSimulator

from .errors import APIError
from app.ai.contracts import InferenceControllerLog, InferenceTelemetryRow

from .schemas import ControllerLog, TelemetryRow
from app.persistence.artifacts import FileArtifactStore
from app.persistence.repository import SQLAlchemyRepository


MAX_ADVANCE_TICKS = 1_000
MAX_RUN_TICKS = 10_000
MAX_PAGE_TICKS = 2_000
MAX_EXPORT_TICKS = 10_000


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


@dataclass
class SimulationRun:
    run_id: str
    simulator: MicrogridSimulator
    created_at: datetime
    updated_at: datetime
    last_command_no: int = 0
    persisted_tick: int = 0
    commands: list[dict] = field(default_factory=list)
    persisted_status: str = "ready"
    error_code: str | None = None
    error_message: str | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def status(self) -> str:
        if self.persisted_status == "failed":
            return "failed"
        return "complete" if self.simulator.tick >= MAX_RUN_TICKS else "ready"


class SimulationService:
    """Persistent run orchestration; mutable simulator access is serialized per run."""

    def __init__(self, repository: SQLAlchemyRepository, artifact_store: FileArtifactStore) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self._runs: dict[str, SimulationRun] = {}
        self._registry_lock = threading.RLock()

    def restore(self) -> None:
        restored: dict[str, SimulationRun] = {}
        for record in self.repository.list_runs_for_restore():
            commands = self.repository.list_commands(record["id"])
            simulator = self._replay(record, commands)
            run = SimulationRun(
                run_id=record["id"],
                simulator=simulator,
                created_at=record["created_at"],
                updated_at=record["updated_at"],
                last_command_no=record["last_command_no"],
                persisted_tick=record["current_tick"],
                commands=commands,
                persisted_status=record["status"],
                error_code=record["error_code"],
                error_message=record["error_message"],
            )
            restored[run.run_id] = run
        with self._registry_lock:
            self._runs = restored

    def _replay(self, record: dict, commands: list[dict] | None = None) -> MicrogridSimulator:
        simulator = MicrogridSimulator(
            GridConfig(**record["config"]), seed=record["seed"]
        )
        if commands is None:
            commands = self.repository.list_commands(record["id"])
        for command in commands:
            if command["command_type"] == "schedule_fault":
                payload = command["payload"]
                simulator.inject(
                    payload["kind"],
                    payload["mode"],
                    severity=payload["severity"],
                    duration_ticks=payload["duration_ticks"],
                    start_tick=payload["start_tick"],
                )
            elif command["command_type"] == "advance":
                if simulator.tick != command["tick"]:
                    raise RuntimeError("Stored simulation command sequence is inconsistent")
                simulator.run(command["payload"]["ticks"])
            elif command["command_type"] == "correct":
                simulator.correct()
        if simulator.tick != record["current_tick"]:
            raise RuntimeError("Stored simulation position is inconsistent")
        return simulator

    def create_run(self, config: GridConfig, seed: int, fault=None) -> SimulationRun:
        simulator = MicrogridSimulator(config=config, seed=seed)
        if fault is not None:
            simulator.inject(
                fault.kind,
                fault.mode,
                severity=fault.severity,
                duration_ticks=fault.duration_ticks,
                start_tick=fault.start_tick,
            )
        now = utc_now()
        run = SimulationRun(str(uuid4()), simulator, now, now)
        topology_path = f"runs/{run.run_id}/topology.json"
        topology_artifact = self.artifact_store.write_json(topology_path, topology_data())
        fault_payload = self._fault_payload(fault) if fault is not None else None
        try:
            self.repository.create_run(
                run_id=run.run_id,
                config=simulator.settings()["config"],
                seed=seed,
                created_at=now,
                initial_fault=fault_payload,
                topology_artifact=self._artifact_data(topology_artifact),
                summary=self._summary(simulator),
            )
        except Exception as exc:
            self.artifact_store.delete(topology_artifact.relative_path)
            raise APIError(
                503, "persistence_unavailable", "Run data could not be saved."
            ) from exc
        run.last_command_no = 1 if fault is not None else 0
        run.persisted_tick = 0
        if fault_payload is not None:
            run.commands.append({
                "sequence": 1,
                "command_type": "schedule_fault",
                "tick": 0,
                "payload": fault_payload,
            })
        with self._registry_lock:
            self._runs[run.run_id] = run
        return run

    @staticmethod
    def _fault_payload(fault) -> dict:
        return {
            "kind": fault.kind.value,
            "mode": fault.mode,
            "severity": fault.severity,
            "duration_ticks": fault.duration_ticks,
            "start_tick": fault.start_tick,
        }

    @staticmethod
    def _artifact_data(artifact) -> dict:
        return {
            "relative_path": artifact.relative_path,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
        }

    @staticmethod
    def _summary(simulator: MicrogridSimulator) -> dict:
        dt = simulator.config.tick_seconds / 3600
        rows = simulator.history
        return {
            "simulated_ticks": len(rows),
            "solar_generated_kwh": sum(row["actual_solar_kw"] for row in rows) * dt,
            "demand_served_kwh": sum(row["delivered_kw"] for row in rows) * dt,
            "unmet_demand_kwh": sum(row["unmet_demand_kw"] for row in rows) * dt,
            "final_soc_pct": (
                rows[-1]["battery_soc_pct"]
                if rows
                else simulator.config.initial_soc_pct
            ),
        }

    def _restore_one(self, run: SimulationRun) -> bool:
        try:
            record = self.repository.get_run(run.run_id)
            if record is None:
                raise LookupError("run not found")
            commands = self.repository.list_commands(run.run_id)
            run.simulator = self._replay(record, commands)
            run.last_command_no = record["last_command_no"]
            run.persisted_tick = record["current_tick"]
            run.commands = commands
            run.persisted_status = record["status"]
            run.error_code = record["error_code"]
            run.error_message = record["error_message"]
            run.updated_at = record["updated_at"]
            return True
        except Exception:
            try:
                fallback = {
                    "id": run.run_id,
                    "config": run.simulator.settings()["config"],
                    "seed": run.simulator.seed,
                    "current_tick": run.persisted_tick,
                }
                run.simulator = self._replay(fallback, run.commands)
                return True
            except Exception:
                run.persisted_status = "failed"
                run.error_code = "recovery_failed"
                run.error_message = "Simulation state could not be restored."
                return False

    def _get_run(self, run_id: str) -> SimulationRun:
        with self._registry_lock:
            run = self._runs.get(run_id)
        if run is None:
            raise APIError(404, "run_not_found", "Simulation run was not found.")
        return run

    def status(self, run_id: str) -> dict:
        run = self._get_run(run_id)
        with run.lock:
            simulator = run.simulator
            return {
                "run_id": run.run_id,
                "status": run.status,
                "seed": simulator.seed,
                "current_tick": simulator.tick,
                "max_ticks": MAX_RUN_TICKS,
                "tick_seconds": simulator.config.tick_seconds,
                "config": simulator.settings()["config"],
                "created_at": utc_iso(run.created_at),
                "updated_at": utc_iso(run.updated_at),
                "error": (
                    {"code": run.error_code, "message": run.error_message}
                    if run.error_code else None
                ),
            }

    def advance(self, run_id: str, ticks: int) -> dict:
        run = self._get_run(run_id)
        with run.lock:
            current_tick = run.simulator.tick
            if run.status == "failed":
                raise APIError(409, "run_failed", "This simulation run has failed.")
            if current_tick + ticks > MAX_RUN_TICKS:
                raise APIError(
                    409,
                    "run_limit_reached",
                    f"A run is limited to {MAX_RUN_TICKS} ticks.",
                )
            start_tick = current_tick
            sequence = run.last_command_no + 1
            try:
                rows = run.simulator.run(ticks)
            except Exception as exc:
                self._restore_one(run)
                run.persisted_status = "failed"
                run.error_code = "simulation_step_failed"
                run.error_message = "Simulation advancement failed."
                run.updated_at = utc_now()
                try:
                    self.repository.mark_failed(
                        run_id=run.run_id,
                        error_code=run.error_code,
                        error_message=run.error_message,
                        updated_at=run.updated_at,
                    )
                except Exception:
                    pass
                raise APIError(500, run.error_code, run.error_message) from exc
            artifact = None
            try:
                artifact = self.artifact_store.write_telemetry_chunk(
                    run.run_id, start_tick, start_tick + ticks, rows
                )
                updated_at = utc_now()
                self.repository.record_advance(
                    run_id=run.run_id,
                    sequence=sequence,
                    start_tick=start_tick,
                    ticks=ticks,
                    telemetry_artifact=self._artifact_data(artifact),
                    summary=self._summary(run.simulator),
                    updated_at=updated_at,
                )
            except Exception as exc:
                if artifact is not None:
                    self.artifact_store.delete(artifact.relative_path)
                self._restore_one(run)
                raise APIError(
                    503, "persistence_unavailable", "Simulation results could not be saved."
                ) from exc
            run.last_command_no = sequence
            run.persisted_tick = start_tick + ticks
            run.commands.append({
                "sequence": sequence,
                "command_type": "advance",
                "tick": start_tick,
                "payload": {"ticks": ticks},
            })
            run.updated_at = updated_at
            return {
                "run_id": run.run_id,
                "status": run.status,
                "advanced_ticks": ticks,
                "current_tick": run.simulator.tick,
            }

    def schedule_fault(self, run_id: str, fault) -> dict:
        run = self._get_run(run_id)
        with run.lock:
            if fault.start_tick < run.simulator.tick:
                raise APIError(
                    422,
                    "fault_start_in_past",
                    "start_tick must be at or after the run's current tick.",
                )
            try:
                run.simulator.inject(
                    fault.kind,
                    fault.mode,
                    severity=fault.severity,
                    duration_ticks=fault.duration_ticks,
                    start_tick=fault.start_tick,
                )
            except ValueError as exc:
                if "Overlapping" in str(exc):
                    raise APIError(
                        409,
                        "fault_schedule_conflict",
                        "Fault schedules may not overlap.",
                    ) from exc
                raise APIError(422, "invalid_fault_schedule", "Fault schedule is invalid.") from exc
            sequence = run.last_command_no + 1
            updated_at = utc_now()
            try:
                self.repository.record_fault_schedule(
                    run_id=run.run_id,
                    sequence=sequence,
                    scheduled_at_tick=run.simulator.tick,
                    fault=self._fault_payload(fault),
                    updated_at=updated_at,
                )
            except Exception as exc:
                self._restore_one(run)
                raise APIError(
                    503, "persistence_unavailable", "Fault schedule could not be saved."
                ) from exc
            run.last_command_no = sequence
            fault_payload = self._fault_payload(fault)
            run.commands.append({
                "sequence": sequence,
                "command_type": "schedule_fault",
                "tick": run.simulator.tick,
                "payload": fault_payload,
            })
            run.updated_at = updated_at
            return {"run_id": run.run_id, "scheduled": True, "start_tick": fault.start_tick}

    def correct(self, run_id: str) -> dict:
        run = self._get_run(run_id)
        with run.lock:
            run.simulator.correct()
            sequence = run.last_command_no + 1
            updated_at = utc_now()
            try:
                self.repository.record_correction(
                    run_id=run.run_id,
                    sequence=sequence,
                    tick=run.simulator.tick,
                    updated_at=updated_at,
                )
            except Exception as exc:
                self._restore_one(run)
                raise APIError(
                    503, "persistence_unavailable", "Correction could not be saved."
                ) from exc
            run.last_command_no = sequence
            run.commands.append({
                "sequence": sequence,
                "command_type": "correct",
                "tick": run.simulator.tick,
                "payload": {},
            })
            run.updated_at = updated_at
            return {"run_id": run.run_id, "corrected": True, "current_tick": run.simulator.tick}

    def _read_range(self, run_id: str, start_tick: int, end_tick: int | None, cap: int):
        run = self._get_run(run_id)
        with run.lock:
            current_tick = run.simulator.tick
            resolved_end = current_tick if end_tick is None else end_tick
            if start_tick > resolved_end or start_tick > current_tick or resolved_end > current_tick:
                raise APIError(
                    422,
                    "invalid_tick_range",
                    "Tick ranges are half-open and must satisfy 0 <= start_tick <= end_tick <= current_tick.",
                )
            if resolved_end - start_tick > cap:
                raise APIError(
                    413,
                    "tick_range_too_large",
                    f"The requested range exceeds the {cap}-tick limit.",
                )
            chunks = self.repository.telemetry_chunks(
                run_id, start_tick, resolved_end
            )
            rows = self.artifact_store.read_telemetry_chunks(
                chunks, start_tick, resolved_end
            )
            return run, resolved_end, rows

    def telemetry(self, run_id: str, start_tick: int, end_tick: int | None) -> dict:
        run, resolved_end, rows = self._read_range(run_id, start_tick, end_tick, MAX_PAGE_TICKS)
        return {"run_id": run.run_id, "start_tick": start_tick, "end_tick": resolved_end, "rows": rows}

    def controller_logs(self, run_id: str, start_tick: int, end_tick: int | None) -> dict:
        run, resolved_end, rows = self._read_range(run_id, start_tick, end_tick, MAX_PAGE_TICKS)
        keys = (
            "tick", "elapsed_seconds", "controller_inputs", "controller_rule",
            "controller_command_kw", "nominal_command_kw", "applied_reserve_soc_pct",
            "applied_discharge_limit_kw", "config_integrity_ok", "inverter_requested_kw",
            "inverter_actual_kw", "message_source_tick", "message_age_seconds",
            "communication_latency_seconds", "packet_dropped", "telemetry_available",
        )
        logs = [{key: row[key] for key in keys} for row in rows]
        return {"run_id": run.run_id, "start_tick": start_tick, "end_tick": resolved_end, "logs": logs}

    def analysis_snapshot(
        self, run_id: str, start_tick: int, end_tick: int | None
    ) -> dict:
        """Freeze an observed-only input window; typed allowlists exclude simulator truth."""
        run, resolved_end, rows = self._read_range(
            run_id, start_tick, end_tick, MAX_PAGE_TICKS
        )
        if start_tick >= resolved_end:
            raise APIError(
                422,
                "invalid_analysis_window",
                "Analysis requires a non-empty tick window already available in the run.",
            )
        # Do not forward the full API telemetry DTO: it includes simulator-only
        # physical state and oracle channels that a field model would not observe.
        telemetry_fields = InferenceTelemetryRow.model_fields.keys()
        controller_fields = InferenceControllerLog.model_fields.keys()
        telemetry = [
            InferenceTelemetryRow.model_validate({key: row[key] for key in telemetry_fields})
            for row in rows
        ]
        logs = [
            InferenceControllerLog.model_validate({key: row[key] for key in controller_fields})
            for row in rows
        ]
        return {
            "simulation_run_id": run.run_id,
            "window": {"start_tick": start_tick, "end_tick": resolved_end},
            "telemetry": [row.model_dump(mode="json") for row in telemetry],
            "controller_logs": [row.model_dump(mode="json") for row in logs],
        }

    def export_metadata(self, run_id: str) -> dict:
        run = self._get_run(run_id)
        with run.lock:
            count = run.simulator.tick
            exports = []
            for format_name, media_type in (
                ("json", "application/json"),
                ("csv", "text/csv; charset=utf-8"),
            ):
                exports.append({
                    "format": format_name,
                    "media_type": media_type,
                    "tick_count": count,
                    "start_tick": 0,
                    "end_tick": count,
                    "generation": "on_demand",
                    "download_path": f"/api/v1/runs/{run.run_id}/exports/{format_name}",
                    "authorization_required": True,
                })
            return {
                "run_id": run.run_id,
                "max_export_ticks": MAX_EXPORT_TICKS,
                "exports": exports,
            }

    def result_metadata(self, run_id: str) -> dict:
        run = self._get_run(run_id)
        with run.lock:
            return {
                "run_id": run.run_id,
                "artifacts": self.repository.result_metadata(run_id),
            }

    def export(self, run_id: str, format_name: str, start_tick: int, end_tick: int | None) -> tuple[str, str]:
        run, resolved_end, rows = self._read_range(
            run_id, start_tick, end_tick, MAX_EXPORT_TICKS
        )
        if format_name == "json":
            return json.dumps(rows, indent=2), "application/json"
        if format_name != "csv":
            raise APIError(404, "export_format_not_found", "Export format was not found.")
        stream = StringIO(newline="")
        fieldnames = list(rows[0]) if rows else list(TelemetryRow.model_fields)
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **row,
                "controller_inputs": json.dumps(row["controller_inputs"]),
            })
        return stream.getvalue(), "text/csv; charset=utf-8"


def fault_catalog() -> dict:
    descriptions = {
        "bias": "Adds severity times PV rating to the measured solar value.",
        "drift": "Ramps measured solar bias over the scheduled duration.",
        "stuck": "Holds the last pre-fault solar reading.",
        "noise": "Adds seeded Gaussian noise scaled by PV rating and severity.",
        "soc_bias": "Adds severity times 60 percentage points to measured SOC.",
        "delay": "Adds ceil(8 times severity) ticks to communication delay.",
        "drop": "Drops packets with the configured fault severity probability.",
        "stale": "Suppresses new messages during the fault interval.",
        "corrupt": "Adds twice severity times PV rating to transmitted solar.",
        "wrong_dispatch": "Requests charging at severity times the configured charge limit.",
        "discharge_limit": "Scales the controller discharge limit by one minus severity.",
        "reserve_threshold": "Raises the controller reserve toward 100 percent.",
        "derate": "Scales the requested inverter target by one minus severity.",
        "shutdown": "Sets inverter AC output to zero during the interval.",
        "efficiency": "Scales inverter efficiency by one minus 0.8 times severity.",
        "inverter_delay": "Blends the current target with the previous target.",
    }
    families = []
    for kind in FaultKind:
        modes = []
        for mode in sorted(MODES[kind]):
            description_key = "inverter_delay" if kind == FaultKind.INVERTER and mode == "delay" else mode
            modes.append({"name": mode, "description": descriptions[description_key]})
        families.append({"name": kind.value, "modes": modes})
    return {
        "fault_types": families,
        "parameters": {
            "severity_min_exclusive": 0,
            "severity_max_inclusive": 1,
            "duration_ticks_min": 1,
            "start_tick_min": 0,
            "start_tick_relation": "must be at or after current_tick",
        },
    }


def topology_data() -> dict:
    from app.propagation import build_topology

    graph = build_topology()
    return {
        "nodes": [
            {"id": node, "label": data["label"]}
            for node, data in graph.nodes(data=True)
        ],
        "edges": [
            {
                "source": source,
                "target": target,
                "kind": data["kind"],
                "dependency": data["dependency"],
                "suspected": data["suspected"],
            }
            for source, target, data in graph.edges(data=True)
        ],
    }


def downstream_data(component: str) -> dict:
    from app.propagation import downstream

    try:
        return {"component": component, "downstream": downstream(component)}
    except ValueError as exc:
        raise APIError(404, "component_not_found", "Component was not found.") from exc
