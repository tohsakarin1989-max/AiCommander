"""agent run observability

Revision ID: e4b5c6d7a812
Revises: c3a8d4f2b711
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4b5c6d7a812"
down_revision: Union[str, None] = "c3a8d4f2b711"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_usage_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_microusd", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_usage_records_id", "agent_usage_records", ["id"], unique=False)
    op.create_index(
        "ix_agent_usage_run_created",
        "agent_usage_records",
        ["run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_usage_provider_created",
        "agent_usage_records",
        ["provider", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_usage_status_created",
        "agent_usage_records",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_usage_status_created", table_name="agent_usage_records")
    op.drop_index("ix_agent_usage_provider_created", table_name="agent_usage_records")
    op.drop_index("ix_agent_usage_run_created", table_name="agent_usage_records")
    op.drop_index("ix_agent_usage_records_id", table_name="agent_usage_records")
    op.drop_table("agent_usage_records")
