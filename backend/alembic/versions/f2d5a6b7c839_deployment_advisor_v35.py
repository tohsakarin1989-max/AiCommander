"""deployment advisor v3.5

Revision ID: f2d5a6b7c839
Revises: e1c4f5a6b728
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2d5a6b7c839"
down_revision: Union[str, None] = "e1c4f5a6b728"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tech_defense_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["operational_area_id"], ["operational_areas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key", "operational_area_id", name="uq_tech_source_area"),
    )
    op.create_table(
        "tech_defense_event_aggregates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_type", sa.String(length=50), nullable=False),
        sa.Column("online_count", sa.Integer(), nullable=False),
        sa.Column("offline_count", sa.Integer(), nullable=False),
        sa.Column("alert_count", sa.Integer(), nullable=False),
        sa.Column("redacted_vehicle_event_count", sa.Integer(), nullable=False),
        sa.Column("disposition_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["operational_area_id"], ["operational_areas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["tech_defense_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "period_start", "period_end", "device_type", name="uq_tech_aggregate_period"),
    )
    op.create_index("ix_tech_aggregate_area_period", "tech_defense_event_aggregates", ["operational_area_id", "period_end"])
    op.create_table(
        "situation_briefs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), nullable=False),
        sa.Column("period_type", sa.String(length=20), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("information_gaps", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["operational_area_id"], ["operational_areas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operational_area_id", "period_type", "input_fingerprint", name="uq_situation_brief_input"),
    )
    op.create_index("ix_situation_briefs_area_period", "situation_briefs", ["operational_area_id", "period_type", "generated_at"])
    op.create_table(
        "deployment_recommendations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("brief_id", sa.String(length=36), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("target_area", sa.String(length=300), nullable=False),
        sa.Column("time_window", sa.String(length=200), nullable=False),
        sa.Column("suggested_action", sa.Text(), nullable=False),
        sa.Column("resource_assumption", sa.Text(), nullable=False),
        sa.Column("expected_effect", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("supporting_evidence", sa.JSON(), nullable=False),
        sa.Column("information_gaps", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("auto_execution_allowed", sa.Boolean(), nullable=False),
        sa.Column("boundary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["brief_id"], ["situation_briefs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brief_id", "rank", name="uq_deployment_recommendation_rank"),
    )
    op.create_index("ix_deployment_recommendations_status", "deployment_recommendations", ["status", "valid_until"])
    op.create_table(
        "recommendation_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recommendation_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("usefulness_score", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["deployment_recommendations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recommendation_feedback_rec", "recommendation_feedback", ["recommendation_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_recommendation_feedback_rec", table_name="recommendation_feedback")
    op.drop_table("recommendation_feedback")
    op.drop_index("ix_deployment_recommendations_status", table_name="deployment_recommendations")
    op.drop_table("deployment_recommendations")
    op.drop_index("ix_situation_briefs_area_period", table_name="situation_briefs")
    op.drop_table("situation_briefs")
    op.drop_index("ix_tech_aggregate_area_period", table_name="tech_defense_event_aggregates")
    op.drop_table("tech_defense_event_aggregates")
    op.drop_table("tech_defense_sources")
