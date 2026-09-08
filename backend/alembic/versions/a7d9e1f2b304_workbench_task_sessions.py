"""workbench task sessions

Revision ID: a7d9e1f2b304
Revises: f6c8d2e4a913
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7d9e1f2b304"
down_revision: Union[str, None] = "f6c8d2e4a913"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workbench_task_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("task_type", sa.String(length=50), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("entry_path", sa.String(length=300), nullable=False),
        sa.Column("last_path", sa.String(length=300), nullable=False),
        sa.Column("page_transitions", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "active_slot", name="uq_workbench_user_active_slot"),
    )
    op.create_index(
        "ix_workbench_sessions_user_status",
        "workbench_task_sessions",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_workbench_sessions_started",
        "workbench_task_sessions",
        ["started_at"],
        unique=False,
    )
    op.create_index(
        "ix_workbench_sessions_task_status",
        "workbench_task_sessions",
        ["task_type", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_workbench_sessions_task_status", table_name="workbench_task_sessions")
    op.drop_index("ix_workbench_sessions_started", table_name="workbench_task_sessions")
    op.drop_index("ix_workbench_sessions_user_status", table_name="workbench_task_sessions")
    op.drop_table("workbench_task_sessions")
