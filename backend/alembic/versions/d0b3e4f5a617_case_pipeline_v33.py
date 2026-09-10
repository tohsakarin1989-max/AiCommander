"""case pipeline v3.3

Revision ID: d0b3e4f5a617
Revises: c9a2d3e4f506
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0b3e4f5a617"
down_revision: Union[str, None] = "c9a2d3e4f506"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_type", sa.String(length=50), nullable=False),
        sa.Column("aggregate_id", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_outbox_status_available", "outbox_events", ["status", "available_at"], unique=False)

    op.create_table(
        "case_pipeline_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=True),
        sa.Column("schema_version", sa.String(length=30), nullable=False),
        sa.Column("dictionary_version", sa.String(length=30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["outbox_events.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id"),
    )
    op.create_index("ix_case_pipeline_states_case_id", "case_pipeline_states", ["case_id"], unique=True)

    op.create_table(
        "case_analysis_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=30), nullable=False),
        sa.Column("dictionary_version", sa.String(length=30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("analysis_readiness", sa.String(length=30), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_id",
            "source_hash",
            "schema_version",
            "dictionary_version",
            name="uq_case_profile_input_version",
        ),
    )
    op.create_index("ix_case_profiles_current", "case_analysis_profiles", ["case_id", "is_current"], unique=False)
    op.create_index(
        "uq_case_profiles_one_current",
        "case_analysis_profiles",
        ["case_id"],
        unique=True,
        postgresql_where=sa.text("is_current IS TRUE"),
        sqlite_where=sa.text("is_current = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_case_profiles_one_current", table_name="case_analysis_profiles")
    op.drop_index("ix_case_profiles_current", table_name="case_analysis_profiles")
    op.drop_table("case_analysis_profiles")
    op.drop_index("ix_case_pipeline_states_case_id", table_name="case_pipeline_states")
    op.drop_table("case_pipeline_states")
    op.drop_index("ix_outbox_status_available", table_name="outbox_events")
    op.drop_table("outbox_events")
