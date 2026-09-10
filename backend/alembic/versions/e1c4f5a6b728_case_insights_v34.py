"""case insights v3.4

Revision ID: e1c4f5a6b728
Revises: d0b3e4f5a617
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1c4f5a6b728"
down_revision: Union[str, None] = "d0b3e4f5a617"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "case_analysis_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("case_profile_id", sa.String(length=36), nullable=False),
        sa.Column("map_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("algorithm_version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("information_gaps", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_profile_id"], ["case_analysis_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["map_snapshot_id"], ["map_snapshots.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_profile_id", "map_snapshot_id", "algorithm_version", name="uq_case_analysis_input_version"),
    )
    op.create_index("ix_case_analysis_case_status", "case_analysis_runs", ["case_id", "status"], unique=False)

    op.create_table(
        "case_hypotheses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("analysis_run_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("hypothesis_type", sa.String(length=40), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("region", sa.JSON(), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("supporting_evidence", sa.JSON(), nullable=False),
        sa.Column("counter_evidence", sa.JSON(), nullable=False),
        sa.Column("information_gaps", sa.JSON(), nullable=False),
        sa.Column("score_components", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("boundary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["case_analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_run_id", "rank", name="uq_case_hypothesis_rank"),
    )
    op.create_index("ix_case_hypotheses_case_type", "case_hypotheses", ["case_id", "hypothesis_type"], unique=False)

    op.create_table(
        "hypothesis_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hypothesis_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["hypothesis_id"], ["case_hypotheses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hypothesis_feedback_hypothesis", "hypothesis_feedback", ["hypothesis_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_hypothesis_feedback_hypothesis", table_name="hypothesis_feedback")
    op.drop_table("hypothesis_feedback")
    op.drop_index("ix_case_hypotheses_case_type", table_name="case_hypotheses")
    op.drop_table("case_hypotheses")
    op.drop_index("ix_case_analysis_case_status", table_name="case_analysis_runs")
    op.drop_table("case_analysis_runs")
