"""SQLAlchemy persistence entities. Scenario records are deliberately separate."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


JSON_VALUE = JSON(none_as_null=True).with_variant(
    JSONB(none_as_null=True), "postgresql"
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SimulationRunRecord(Base):
    __tablename__ = "simulation_runs"
    __table_args__ = (
        CheckConstraint("status IN ('ready', 'complete', 'failed')", name="ck_run_status"),
        CheckConstraint("current_tick >= 0 AND current_tick <= 10000", name="ck_run_tick_bounds"),
        Index("ix_simulation_runs_status_created", "status", "created_at"),
        Index("ix_simulation_runs_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(128))
    config: Mapped[dict] = mapped_column(JSON_VALUE, nullable=False)
    # Text preserves the Python RNG's full supported integer seed range.
    seed: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    current_tick: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_command_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    fault_scenarios: Mapped[list["FaultScenarioRecord"]] = relationship(back_populates="run")
    commands: Mapped[list["SimulationCommandRecord"]] = relationship(back_populates="run")
    result_metadata: Mapped[list["SimulationResultMetadataRecord"]] = relationship(back_populates="run")
    incidents: Mapped[list["IncidentRecord"]] = relationship(back_populates="run")
    analyses: Mapped[list["AIAnalysisRecord"]] = relationship(back_populates="run")


class FaultScenarioRecord(Base):
    __tablename__ = "fault_scenarios"
    __table_args__ = (
        CheckConstraint("severity > 0 AND severity <= 1", name="ck_fault_severity"),
        CheckConstraint("duration_ticks >= 1", name="ck_fault_duration"),
        CheckConstraint("start_tick >= 0 AND scheduled_at_tick >= 0", name="ck_fault_ticks"),
        UniqueConstraint("run_id", "ordinal", name="uq_fault_run_ordinal"),
        Index("ix_fault_scenarios_run_start", "run_id", "start_tick"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("simulation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    fault_type: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[float] = mapped_column(Float, nullable=False)
    duration_ticks: Mapped[int] = mapped_column(Integer, nullable=False)
    start_tick: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_at_tick: Mapped[int] = mapped_column(Integer, nullable=False)
    cancelled_at_tick: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    run: Mapped[SimulationRunRecord] = relationship(back_populates="fault_scenarios")


class SimulationCommandRecord(Base):
    """Restricted replay journal, including scenario controls; never an API DTO."""

    __tablename__ = "simulation_commands"
    __table_args__ = (
        CheckConstraint(
            "command_type IN ('schedule_fault', 'advance', 'correct')",
            name="ck_simulation_command_type",
        ),
        CheckConstraint("tick >= 0 AND sequence >= 1", name="ck_simulation_command_order"),
        UniqueConstraint("run_id", "sequence", name="uq_command_run_sequence"),
        Index("ix_simulation_commands_run_sequence", "run_id", "sequence"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("simulation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    command_type: Mapped[str] = mapped_column(String(32), nullable=False)
    tick: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON_VALUE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    run: Mapped[SimulationRunRecord] = relationship(back_populates="commands")


class SimulationResultMetadataRecord(Base):
    __tablename__ = "simulation_result_metadata"
    __table_args__ = (
        CheckConstraint(
            "artifact_type IN ('telemetry', 'controller_logs', 'topology_snapshot', 'output_summary')",
            name="ck_result_artifact_type",
        ),
        CheckConstraint("storage_type IN ('file', 'derived', 'json')", name="ck_result_storage_type"),
        CheckConstraint("size_bytes >= 0", name="ck_result_size_nonnegative"),
        CheckConstraint(
            "tick_start IS NULL OR (tick_start >= 0 AND tick_end >= tick_start)",
            name="ck_result_tick_range",
        ),
        UniqueConstraint(
            "run_id", "artifact_type", "tick_start", "tick_end",
            name="uq_result_run_type_range",
        ),
        Index("ix_result_metadata_run_type", "run_id", "artifact_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("simulation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_type: Mapped[str] = mapped_column(String(16), nullable=False)
    relative_path: Mapped[str | None] = mapped_column(String(500))
    source_artifact_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("simulation_result_metadata.id", ondelete="RESTRICT")
    )
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tick_start: Mapped[int | None] = mapped_column(Integer)
    tick_end: Mapped[int | None] = mapped_column(Integer)
    output_summary: Mapped[dict | None] = mapped_column(JSON_VALUE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    run: Mapped[SimulationRunRecord] = relationship(back_populates="result_metadata")


class IncidentRecord(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(
            "investigation_status IN ('open', 'investigating', 'resolved', 'closed')",
            name="ck_incident_status",
        ),
        CheckConstraint("length(title) BETWEEN 1 AND 200", name="ck_incident_title_length"),
        CheckConstraint("length(category) BETWEEN 1 AND 100", name="ck_incident_category_length"),
        Index("ix_incidents_status_created", "investigation_status", "created_at"),
        Index("ix_incidents_component_category", "affected_component", "category"),
        Index("ix_incidents_run", "simulation_run_id"),
        Index("ix_incidents_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(128))
    simulation_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("simulation_runs.id", ondelete="RESTRICT")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    affected_component: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    observed_evidence: Mapped[dict] = mapped_column(JSON_VALUE, nullable=False, default=dict)
    priority: Mapped[str | None] = mapped_column(String(40))
    investigation_status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    run: Mapped[SimulationRunRecord | None] = relationship(back_populates="incidents")
    analyses: Mapped[list["AIAnalysisRecord"]] = relationship(back_populates="incident")


class AIAnalysisRecord(Base):
    __tablename__ = "ai_analysis_records"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_ai_analysis_status",
        ),
        CheckConstraint(
            "simulation_run_id IS NOT NULL OR incident_id IS NOT NULL",
            name="ck_ai_analysis_context",
        ),
        CheckConstraint(
            "status != 'completed' OR validated_output IS NOT NULL",
            name="ck_ai_analysis_completed_output",
        ),
        Index("uq_ai_analysis_owner_idempotency_key", "owner_id", "idempotency_key", unique=True),
        Index("ix_ai_analysis_run_status", "simulation_run_id", "status"),
        Index("ix_ai_analysis_incident_status", "incident_id", "status"),
        Index("ix_ai_analysis_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(128))
    simulation_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("simulation_runs.id", ondelete="RESTRICT")
    )
    incident_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    model_name: Mapped[str | None] = mapped_column(String(120))
    model_version: Mapped[str | None] = mapped_column(String(120))
    provider_name: Mapped[str | None] = mapped_column(String(120))
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    validated_output: Mapped[dict | None] = mapped_column(JSON_VALUE)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    input_sha256: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[SimulationRunRecord | None] = relationship(back_populates="analyses")
    incident: Mapped[IncidentRecord | None] = relationship(back_populates="analyses")
