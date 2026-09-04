"""agent lab runtime foundation

Revision ID: c3a8d4f2b711
Revises: a2f6c1d9e403
Create Date: 2026-09-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c3a8d4f2b711"
down_revision = "a2f6c1d9e403"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    existing = set(_inspector().get_table_names())
    if "agent_runs" not in existing:
        op.create_table(
            "agent_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("task_type", sa.String(length=50), nullable=False),
            sa.Column("query", sa.Text(), nullable=False),
            sa.Column("case_ids", sa.JSON(), nullable=False),
            sa.Column("asset_ids", sa.JSON(), nullable=False),
            sa.Column("mode", sa.String(length=20), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("model_provider", sa.String(length=50), nullable=True),
            sa.Column("model_name", sa.String(length=100), nullable=True),
            sa.Column("data_version", sa.String(length=64), nullable=False),
            sa.Column("input_payload", sa.JSON(), nullable=False),
            sa.Column("result_summary", sa.JSON(), nullable=False),
            sa.Column("runtime_state", sa.JSON(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("replay_of_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["replay_of_id"], ["agent_runs.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_agent_runs_task_type", "agent_runs", ["task_type"])
        op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
        op.create_index("ix_agent_runs_status_created", "agent_runs", ["status", "created_at"])
        op.create_index("ix_agent_runs_created_by", "agent_runs", ["created_by"])

    if "agent_events" not in existing:
        op.create_table(
            "agent_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.String(length=36), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=60), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=True),
            sa.Column("actor_type", sa.String(length=30), nullable=False),
            sa.Column("actor_name", sa.String(length=100), nullable=True),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("input_summary", sa.JSON(), nullable=False),
            sa.Column("output_summary", sa.JSON(), nullable=False),
            sa.Column("evidence_refs", sa.JSON(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", "sequence", name="uq_agent_events_run_sequence"),
        )
        op.create_index("ix_agent_events_event_type", "agent_events", ["event_type"])
        op.create_index("ix_agent_events_run_created", "agent_events", ["run_id", "created_at"])

    if "agent_artifacts" not in existing:
        op.create_table(
            "agent_artifacts",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("run_id", sa.String(length=36), nullable=False),
            sa.Column("artifact_type", sa.String(length=50), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("content", sa.JSON(), nullable=False),
            sa.Column("evidence_refs", sa.JSON(), nullable=False),
            sa.Column("source_signature", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", "artifact_type", "version", name="uq_agent_artifact_version"),
        )
        op.create_index("ix_agent_artifacts_run_type", "agent_artifacts", ["run_id", "artifact_type"])

    if "agent_approvals" not in existing:
        op.create_table(
            "agent_approvals",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("run_id", sa.String(length=36), nullable=False),
            sa.Column("artifact_id", sa.String(length=36), nullable=False),
            sa.Column("action_type", sa.String(length=50), nullable=False),
            sa.Column("target_type", sa.String(length=50), nullable=False),
            sa.Column("target_id", sa.Integer(), nullable=False),
            sa.Column("candidate_patch", sa.JSON(), nullable=False),
            sa.Column("source_signature", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("requested_by", sa.Integer(), nullable=True),
            sa.Column("decided_by", sa.Integer(), nullable=True),
            sa.Column("decision_comment", sa.Text(), nullable=True),
            sa.Column("idempotency_key", sa.String(length=64), nullable=False),
            sa.Column("execution_result", sa.JSON(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["artifact_id"], ["agent_artifacts.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("idempotency_key", name="uq_agent_approvals_idempotency"),
        )
        op.create_index("ix_agent_approvals_status", "agent_approvals", ["status"])
        op.create_index("ix_agent_approvals_run_status", "agent_approvals", ["run_id", "status"])
        op.create_index("ix_agent_approvals_expires_at", "agent_approvals", ["expires_at"])


def downgrade() -> None:
    existing = set(_inspector().get_table_names())
    for table_name in ("agent_approvals", "agent_artifacts", "agent_events", "agent_runs"):
        if table_name in existing:
            op.drop_table(table_name)
