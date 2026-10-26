"""Add bounded AI job metadata and idempotency fields.

Revision ID: 0002_ai_integration
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_ai_integration"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_analysis_records", sa.Column("provider_name", sa.String(length=120)))
    op.add_column("ai_analysis_records", sa.Column("idempotency_key", sa.String(length=128)))
    op.add_column("ai_analysis_records", sa.Column("input_sha256", sa.String(length=64)))
    op.add_column("ai_analysis_records", sa.Column("started_at", sa.DateTime(timezone=True)))
    op.create_index(
        "uq_ai_analysis_idempotency_key", "ai_analysis_records", ["idempotency_key"], unique=True
    )


def downgrade() -> None:
    raise RuntimeError(
        "This migration is intentionally non-reversible to protect persistent analysis records."
    )
