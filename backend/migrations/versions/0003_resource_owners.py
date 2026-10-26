"""Add principal ownership boundaries to private resources.

Existing records stay intact and ownerless. The API deliberately does not expose
legacy ownerless records; operators may assign them through an audited process.
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_resource_owners"
down_revision = "0002_ai_integration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("simulation_runs", sa.Column("owner_id", sa.String(length=128), nullable=True))
    op.add_column("incidents", sa.Column("owner_id", sa.String(length=128), nullable=True))
    op.add_column("ai_analysis_records", sa.Column("owner_id", sa.String(length=128), nullable=True))
    op.drop_index("uq_ai_analysis_idempotency_key", table_name="ai_analysis_records")
    op.create_index(
        "uq_ai_analysis_owner_idempotency_key",
        "ai_analysis_records",
        ["owner_id", "idempotency_key"],
        unique=True,
    )
    op.create_index("ix_simulation_runs_owner_created", "simulation_runs", ["owner_id", "created_at"])
    op.create_index("ix_incidents_owner_created", "incidents", ["owner_id", "created_at"])
    op.create_index("ix_ai_analysis_owner_created", "ai_analysis_records", ["owner_id", "created_at"])


def downgrade() -> None:
    raise RuntimeError(
        "This migration is intentionally non-reversible to protect ownership metadata and application data."
    )
