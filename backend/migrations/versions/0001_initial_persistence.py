"""Create persistent run, artifact, incident, and analysis entities.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    op.create_table(
        "simulation_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("config", JSON_VALUE, nullable=False),
        sa.Column("seed", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_tick", sa.Integer(), nullable=False),
        sa.Column("last_command_no", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("error_message", sa.String(length=500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('ready', 'complete', 'failed')", name="ck_run_status"),
        sa.CheckConstraint("current_tick >= 0 AND current_tick <= 10000", name="ck_run_tick_bounds"),
    )
    op.create_index("ix_simulation_runs_status_created", "simulation_runs", ["status", "created_at"])

    op.create_table(
        "fault_scenarios",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("simulation_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("fault_type", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.Float(), nullable=False),
        sa.Column("duration_ticks", sa.Integer(), nullable=False),
        sa.Column("start_tick", sa.Integer(), nullable=False),
        sa.Column("scheduled_at_tick", sa.Integer(), nullable=False),
        sa.Column("cancelled_at_tick", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("severity > 0 AND severity <= 1", name="ck_fault_severity"),
        sa.CheckConstraint("duration_ticks >= 1", name="ck_fault_duration"),
        sa.CheckConstraint("start_tick >= 0 AND scheduled_at_tick >= 0", name="ck_fault_ticks"),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_fault_run_ordinal"),
    )
    op.create_index("ix_fault_scenarios_run_start", "fault_scenarios", ["run_id", "start_tick"])

    op.create_table(
        "simulation_commands",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("simulation_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("command_type", sa.String(length=32), nullable=False),
        sa.Column("tick", sa.Integer(), nullable=False),
        sa.Column("payload", JSON_VALUE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("command_type IN ('schedule_fault', 'advance', 'correct')", name="ck_simulation_command_type"),
        sa.CheckConstraint("tick >= 0 AND sequence >= 1", name="ck_simulation_command_order"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_command_run_sequence"),
    )
    op.create_index("ix_simulation_commands_run_sequence", "simulation_commands", ["run_id", "sequence"])

    op.create_table(
        "simulation_result_metadata",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("simulation_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("storage_type", sa.String(length=16), nullable=False),
        sa.Column("relative_path", sa.String(length=500)),
        sa.Column("source_artifact_id", sa.String(length=36), sa.ForeignKey("simulation_result_metadata.id", ondelete="RESTRICT")),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("sha256", sa.String(length=64)),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("tick_start", sa.Integer()),
        sa.Column("tick_end", sa.Integer()),
        sa.Column("output_summary", JSON_VALUE),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("artifact_type IN ('telemetry', 'controller_logs', 'topology_snapshot', 'output_summary')", name="ck_result_artifact_type"),
        sa.CheckConstraint("storage_type IN ('file', 'derived', 'json')", name="ck_result_storage_type"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_result_size_nonnegative"),
        sa.CheckConstraint("tick_start IS NULL OR (tick_start >= 0 AND tick_end >= tick_start)", name="ck_result_tick_range"),
        sa.UniqueConstraint("run_id", "artifact_type", "tick_start", "tick_end", name="uq_result_run_type_range"),
    )
    op.create_index("ix_result_metadata_run_type", "simulation_result_metadata", ["run_id", "artifact_type"])

    op.create_table(
        "incidents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("simulation_run_id", sa.String(length=36), sa.ForeignKey("simulation_runs.id", ondelete="RESTRICT")),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("affected_component", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("observed_evidence", JSON_VALUE, nullable=False),
        sa.Column("priority", sa.String(length=40)),
        sa.Column("investigation_status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("investigation_status IN ('open', 'investigating', 'resolved', 'closed')", name="ck_incident_status"),
        sa.CheckConstraint("length(title) BETWEEN 1 AND 200", name="ck_incident_title_length"),
        sa.CheckConstraint("length(category) BETWEEN 1 AND 100", name="ck_incident_category_length"),
    )
    op.create_index("ix_incidents_status_created", "incidents", ["investigation_status", "created_at"])
    op.create_index("ix_incidents_component_category", "incidents", ["affected_component", "category"])
    op.create_index("ix_incidents_run", "incidents", ["simulation_run_id"])

    op.create_table(
        "ai_analysis_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("simulation_run_id", sa.String(length=36), sa.ForeignKey("simulation_runs.id", ondelete="RESTRICT")),
        sa.Column("incident_id", sa.String(length=36), sa.ForeignKey("incidents.id", ondelete="RESTRICT")),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("model_name", sa.String(length=120)),
        sa.Column("model_version", sa.String(length=120)),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("validated_output", JSON_VALUE),
        sa.Column("failure_code", sa.String(length=80)),
        sa.Column("failure_message", sa.String(length=500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="ck_ai_analysis_status"),
        sa.CheckConstraint("simulation_run_id IS NOT NULL OR incident_id IS NOT NULL", name="ck_ai_analysis_context"),
        sa.CheckConstraint("status != 'completed' OR validated_output IS NOT NULL", name="ck_ai_analysis_completed_output"),
    )
    op.create_index("ix_ai_analysis_run_status", "ai_analysis_records", ["simulation_run_id", "status"])
    op.create_index("ix_ai_analysis_incident_status", "ai_analysis_records", ["incident_id", "status"])


def downgrade() -> None:
    raise RuntimeError(
        "This initial migration is intentionally non-reversible to protect persistent application data."
    )
