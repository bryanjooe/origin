"""Persistence operations, transactions, and query boundaries."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    AIAnalysisRecord,
    FaultScenarioRecord,
    IncidentRecord,
    SimulationCommandRecord,
    SimulationResultMetadataRecord,
    SimulationRunRecord,
)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class SQLAlchemyRepository:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    def check_ready(self) -> None:
        with self.sessions() as session:
            session.execute(select(SimulationRunRecord.id).limit(1)).all()
            session.execute(select(SimulationCommandRecord.id).limit(1)).all()
            session.execute(select(FaultScenarioRecord.id).limit(1)).all()
            session.execute(select(SimulationResultMetadataRecord.id).limit(1)).all()
            session.execute(select(IncidentRecord.id).limit(1)).all()
            session.execute(select(AIAnalysisRecord.id).limit(1)).all()

    def create_run(
        self,
        *,
        run_id: str,
        config: dict,
        seed: int,
        created_at: datetime,
        initial_fault: dict | None,
        topology_artifact: dict,
        summary: dict,
    ) -> None:
        with self.sessions.begin() as session:
            run = SimulationRunRecord(
                id=run_id,
                config=config,
                seed=str(seed),
                status="ready",
                current_tick=0,
                last_command_no=0,
                created_at=created_at,
                updated_at=created_at,
            )
            session.add(run)
            session.flush()
            if initial_fault is not None:
                self._add_fault(session, run_id, initial_fault, 0)
                session.add(SimulationCommandRecord(
                    run_id=run_id,
                    sequence=1,
                    command_type="schedule_fault",
                    tick=0,
                    payload=initial_fault,
                ))
                run.last_command_no = 1
            session.add(self._artifact_row(
                run_id,
                artifact_type="topology_snapshot",
                storage_type="file",
                artifact=topology_artifact,
                media_type="application/json",
                tick_start=0,
                tick_end=0,
            ))
            session.add(SimulationResultMetadataRecord(
                id=str(uuid4()),
                run_id=run_id,
                artifact_type="output_summary",
                storage_type="json",
                media_type="application/json",
                sha256=None,
                size_bytes=0,
                tick_start=0,
                tick_end=0,
                output_summary=summary,
            ))

    def get_run(self, run_id: str) -> dict | None:
        with self.sessions() as session:
            record = session.get(SimulationRunRecord, run_id)
            return self._run_dict(record) if record else None

    def list_runs_for_restore(self) -> list[dict]:
        with self.sessions() as session:
            records = session.scalars(
                select(SimulationRunRecord).order_by(SimulationRunRecord.created_at)
            ).all()
            return [self._run_dict(record) for record in records]

    def list_commands(self, run_id: str) -> list[dict]:
        with self.sessions() as session:
            commands = session.scalars(
                select(SimulationCommandRecord)
                .where(SimulationCommandRecord.run_id == run_id)
                .order_by(SimulationCommandRecord.sequence)
            ).all()
            return [
                {
                    "sequence": command.sequence,
                    "command_type": command.command_type,
                    "tick": command.tick,
                    "payload": command.payload,
                }
                for command in commands
            ]

    def record_fault_schedule(
        self,
        *,
        run_id: str,
        sequence: int,
        scheduled_at_tick: int,
        fault: dict,
        updated_at: datetime,
    ) -> None:
        with self.sessions.begin() as session:
            run = session.get(SimulationRunRecord, run_id)
            if run is None:
                raise LookupError("run not found")
            ordinal = session.scalar(
                select(func.coalesce(func.max(FaultScenarioRecord.ordinal), 0)).where(
                    FaultScenarioRecord.run_id == run_id
                )
            ) + 1
            self._add_fault(session, run_id, fault, scheduled_at_tick, ordinal=ordinal)
            session.add(SimulationCommandRecord(
                run_id=run_id,
                sequence=sequence,
                command_type="schedule_fault",
                tick=scheduled_at_tick,
                payload=fault,
            ))
            run.last_command_no = sequence
            run.updated_at = updated_at

    def record_advance(
        self,
        *,
        run_id: str,
        sequence: int,
        start_tick: int,
        ticks: int,
        telemetry_artifact: dict,
        summary: dict,
        updated_at: datetime,
    ) -> None:
        end_tick = start_tick + ticks
        with self.sessions.begin() as session:
            run = session.get(SimulationRunRecord, run_id)
            if run is None:
                raise LookupError("run not found")
            session.add(SimulationCommandRecord(
                run_id=run_id,
                sequence=sequence,
                command_type="advance",
                tick=start_tick,
                payload={"ticks": ticks},
            ))
            telemetry = self._artifact_row(
                run_id,
                artifact_type="telemetry",
                storage_type="file",
                artifact=telemetry_artifact,
                media_type="application/x-ndjson",
                tick_start=start_tick,
                tick_end=end_tick,
            )
            session.add(telemetry)
            session.flush()
            session.add(SimulationResultMetadataRecord(
                id=str(uuid4()),
                run_id=run_id,
                artifact_type="controller_logs",
                storage_type="derived",
                source_artifact_id=telemetry.id,
                media_type="application/json",
                sha256=None,
                size_bytes=0,
                tick_start=start_tick,
                tick_end=end_tick,
            ))
            summary_record = session.scalar(
                select(SimulationResultMetadataRecord).where(
                    SimulationResultMetadataRecord.run_id == run_id,
                    SimulationResultMetadataRecord.artifact_type == "output_summary",
                )
            )
            summary_record.output_summary = summary
            summary_record.tick_end = end_tick
            run.current_tick = end_tick
            run.status = "complete" if end_tick >= 10_000 else "ready"
            run.last_command_no = sequence
            run.updated_at = updated_at

    def record_correction(
        self, *, run_id: str, sequence: int, tick: int, updated_at: datetime
    ) -> None:
        with self.sessions.begin() as session:
            run = session.get(SimulationRunRecord, run_id)
            if run is None:
                raise LookupError("run not found")
            session.add(SimulationCommandRecord(
                run_id=run_id,
                sequence=sequence,
                command_type="correct",
                tick=tick,
                payload={},
            ))
            session.execute(
                update(FaultScenarioRecord)
                .where(
                    FaultScenarioRecord.run_id == run_id,
                    FaultScenarioRecord.cancelled_at_tick.is_(None),
                    FaultScenarioRecord.start_tick + FaultScenarioRecord.duration_ticks > tick,
                )
                .values(cancelled_at_tick=tick)
            )
            run.last_command_no = sequence
            run.updated_at = updated_at

    def mark_failed(
        self, *, run_id: str, error_code: str, error_message: str, updated_at: datetime
    ) -> None:
        with self.sessions.begin() as session:
            run = session.get(SimulationRunRecord, run_id)
            if run is not None:
                run.status = "failed"
                run.error_code = error_code
                run.error_message = error_message
                run.updated_at = updated_at

    def telemetry_chunks(self, run_id: str, start_tick: int, end_tick: int) -> list[dict]:
        with self.sessions() as session:
            rows = session.scalars(
                select(SimulationResultMetadataRecord)
                .where(
                    SimulationResultMetadataRecord.run_id == run_id,
                    SimulationResultMetadataRecord.artifact_type == "telemetry",
                    SimulationResultMetadataRecord.tick_start < end_tick,
                    SimulationResultMetadataRecord.tick_end > start_tick,
                )
                .order_by(SimulationResultMetadataRecord.tick_start)
            ).all()
            return [
                {
                    "relative_path": row.relative_path,
                    "tick_start": row.tick_start,
                    "tick_end": row.tick_end,
                    "sha256": row.sha256,
                    "size_bytes": row.size_bytes,
                }
                for row in rows
            ]

    def result_metadata(self, run_id: str) -> list[dict]:
        with self.sessions() as session:
            rows = session.scalars(
                select(SimulationResultMetadataRecord)
                .where(SimulationResultMetadataRecord.run_id == run_id)
                .order_by(SimulationResultMetadataRecord.created_at)
            ).all()
            return [
                {
                    "artifact_type": row.artifact_type,
                    "storage_type": row.storage_type,
                    "tick_start": row.tick_start,
                    "tick_end": row.tick_end,
                    "media_type": row.media_type,
                    "size_bytes": row.size_bytes,
                    "sha256": row.sha256,
                    "output_summary": row.output_summary,
                }
                for row in rows
            ]

    def create_incident(self, values: dict) -> dict | None:
        with self.sessions.begin() as session:
            if values.get("simulation_run_id") and session.get(
                SimulationRunRecord, values["simulation_run_id"]
            ) is None:
                return None
            record = IncidentRecord(id=str(uuid4()), **values)
            session.add(record)
            session.flush()
            return self._incident_dict(record)

    def get_incident(self, incident_id: str) -> dict | None:
        with self.sessions() as session:
            record = session.get(IncidentRecord, incident_id)
            return self._incident_dict(record) if record else None

    def list_incidents(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        category: str | None = None,
        affected_component: str | None = None,
        simulation_run_id: str | None = None,
    ) -> tuple[list[dict], int]:
        with self.sessions() as session:
            statement = select(IncidentRecord)
            count_statement = select(func.count()).select_from(IncidentRecord)
            filters = []
            if status is not None:
                filters.append(IncidentRecord.investigation_status == status)
            if category is not None:
                filters.append(IncidentRecord.category == category)
            if affected_component is not None:
                filters.append(IncidentRecord.affected_component == affected_component)
            if simulation_run_id is not None:
                filters.append(IncidentRecord.simulation_run_id == simulation_run_id)
            if filters:
                statement = statement.where(*filters)
                count_statement = count_statement.where(*filters)
            total = session.scalar(count_statement) or 0
            records = session.scalars(
                statement.order_by(IncidentRecord.created_at.desc(), IncidentRecord.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return [self._incident_dict(record) for record in records], total

    def update_incident(self, incident_id: str, changes: dict) -> dict | None:
        with self.sessions.begin() as session:
            record = session.get(IncidentRecord, incident_id)
            if record is None:
                return None
            for key, value in changes.items():
                setattr(record, key, value)
            record.updated_at = datetime.now(timezone.utc)
            session.flush()
            return self._incident_dict(record)

    def create_analysis(
        self,
        *,
        analysis_id: str,
        run_id: str | None,
        incident_id: str | None,
        status: str,
        model_name: str | None,
        model_version: str | None,
        schema_version: str,
        validated_output: dict | None,
        idempotency_key: str | None = None,
        input_sha256: str | None = None,
        provider_name: str | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> tuple[str, bool]:
        try:
            with self.sessions.begin() as session:
                record = AIAnalysisRecord(
                    id=analysis_id,
                    simulation_run_id=run_id,
                    incident_id=incident_id,
                    status=status,
                    model_name=model_name,
                    model_version=model_version,
                    provider_name=provider_name,
                    schema_version=schema_version,
                    validated_output=validated_output,
                    idempotency_key=idempotency_key,
                    input_sha256=input_sha256,
                    failure_code=failure_code,
                    failure_message=failure_message,
                    completed_at=datetime.now(timezone.utc) if status == "completed" else None,
                )
                session.add(record)
            return analysis_id, True
        except IntegrityError:
            if idempotency_key is None:
                raise
            with self.sessions() as session:
                existing = session.scalar(select(AIAnalysisRecord).where(
                    AIAnalysisRecord.idempotency_key == idempotency_key
                ))
                if existing is None:
                    raise
                if existing.input_sha256 != input_sha256:
                    raise AnalysisIdempotencyConflict(
                        "Idempotency key was already used for different analysis input."
                    )
                return existing.id, False

    def update_analysis(self, analysis_id: str, changes: dict) -> bool:
        with self.sessions.begin() as session:
            record = session.get(AIAnalysisRecord, analysis_id)
            if record is None:
                return False
            for key, value in changes.items():
                setattr(record, key, value)
            if record.status == "running" and record.started_at is None:
                record.started_at = datetime.now(timezone.utc)
            record.updated_at = datetime.now(timezone.utc)
            if record.status == "completed":
                record.completed_at = record.updated_at
            session.flush()
            return True

    def get_analysis(self, analysis_id: str) -> dict | None:
        with self.sessions() as session:
            record = session.get(AIAnalysisRecord, analysis_id)
            if record is None:
                return None
            return {
                "id": record.id,
                "simulation_run_id": record.simulation_run_id,
                "incident_id": record.incident_id,
                "status": record.status,
                "model_name": record.model_name,
                "model_version": record.model_version,
                "provider_name": record.provider_name,
                "schema_version": record.schema_version,
                "validated_output": record.validated_output,
                "failure_code": record.failure_code,
                "failure_message": record.failure_message,
                "created_at": _iso(record.created_at),
                "updated_at": _iso(record.updated_at),
                "started_at": _iso(record.started_at),
                "completed_at": _iso(record.completed_at),
            }

    def fail_interrupted_analyses(self) -> None:
        """Mark in-process jobs from a prior server process as interrupted."""
        with self.sessions.begin() as session:
            session.execute(
                update(AIAnalysisRecord)
                .where(AIAnalysisRecord.status.in_(("pending", "running")))
                .values(
                    status="failed",
                    failure_code="worker_interrupted",
                    failure_message="Analysis worker stopped before completion.",
                    updated_at=datetime.now(timezone.utc),
                )
            )

    @staticmethod
    def _add_fault(
        session: Session,
        run_id: str,
        fault: dict,
        scheduled_at_tick: int,
        ordinal: int | None = None,
    ) -> None:
        if ordinal is None:
            ordinal = (session.scalar(
                select(func.coalesce(func.max(FaultScenarioRecord.ordinal), 0)).where(
                    FaultScenarioRecord.run_id == run_id
                )
            ) or 0) + 1
        session.add(FaultScenarioRecord(
            id=str(uuid4()),
            run_id=run_id,
            ordinal=ordinal,
            fault_type=str(fault["kind"]),
            mode=fault["mode"],
            severity=fault["severity"],
            duration_ticks=fault["duration_ticks"],
            start_tick=fault["start_tick"],
            scheduled_at_tick=scheduled_at_tick,
        ))

    @staticmethod
    def _artifact_row(
        run_id: str,
        *,
        artifact_type: str,
        storage_type: str,
        artifact: dict,
        media_type: str,
        tick_start: int | None,
        tick_end: int | None,
    ) -> SimulationResultMetadataRecord:
        return SimulationResultMetadataRecord(
            id=str(uuid4()),
            run_id=run_id,
            artifact_type=artifact_type,
            storage_type=storage_type,
            relative_path=artifact["relative_path"],
            media_type=media_type,
            sha256=artifact["sha256"],
            size_bytes=artifact["size_bytes"],
            tick_start=tick_start,
            tick_end=tick_end,
        )

    @staticmethod
    def _run_dict(record: SimulationRunRecord) -> dict:
        return {
            "id": record.id,
            "config": record.config,
            "seed": int(record.seed),
            "status": record.status,
            "current_tick": record.current_tick,
            "last_command_no": record.last_command_no,
            "error_code": record.error_code,
            "error_message": record.error_message,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    @staticmethod
    def _incident_dict(record: IncidentRecord) -> dict:
        return {
            "id": record.id,
            "simulation_run_id": record.simulation_run_id,
            "title": record.title,
            "affected_component": record.affected_component,
            "category": record.category,
            "description": record.description,
            "observed_evidence": record.observed_evidence,
            "priority": record.priority,
            "investigation_status": record.investigation_status,
            "created_at": _iso(record.created_at),
            "updated_at": _iso(record.updated_at),
        }


class AnalysisIdempotencyConflict(ValueError):
    """A client reused an idempotency key for a different frozen input window."""
