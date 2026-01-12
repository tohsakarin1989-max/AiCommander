"""init schema

Revision ID: 4b0f2d2a4e5a
Revises: None
Create Date: 2025-01-15 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "4b0f2d2a4e5a"
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in inspector.get_table_names()

def _fk_exists(table_name: str, fk_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for fk in inspector.get_foreign_keys(table_name):
        if fk.get("name") == fk_name:
            return True
    return False

def upgrade() -> None:
    if not _table_exists("cases"):
        op.create_table(
            "cases",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("case_number", sa.String(length=50), nullable=False),
            sa.Column("occurred_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("location", sa.String(length=200)),
            sa.Column("latitude", sa.Float()),
            sa.Column("longitude", sa.Float()),
            sa.Column("case_type", sa.String(length=50)),
            sa.Column("description", sa.Text()),
            sa.Column("involved_persons", sa.JSON()),
            sa.Column("involved_items", sa.JSON()),
            sa.Column("loss_amount", sa.Integer()),
            sa.Column("oil_type", sa.String(length=50)),
            sa.Column("oil_volume", sa.Float()),
            sa.Column("oil_value", sa.Integer()),
            sa.Column("facility_type", sa.String(length=50)),
            sa.Column("facility_owner", sa.String(length=100)),
            sa.Column("security_level", sa.String(length=50)),
            sa.Column("modus_operandi", sa.String(length=200)),
            sa.Column("suspect_roles", sa.JSON()),
            sa.Column("vehicle_info", sa.JSON()),
            sa.Column("upstream_source", sa.String(length=200)),
            sa.Column("downstream_destination", sa.String(length=200)),
            sa.Column("status", sa.String(length=20)),
            sa.Column("features", sa.JSON()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("case_number", name="uq_cases_case_number"),
        )
        op.create_index("ix_cases_case_number", "cases", ["case_number"])

    if not _table_exists("ai_models"):
        op.create_table(
            "ai_models",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("provider", sa.String(length=50), nullable=False),
            sa.Column("model_name", sa.String(length=100), nullable=False),
            sa.Column("api_key", sa.Text(), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("1")),
            sa.Column("is_default", sa.Boolean(), server_default=sa.text("0")),
            sa.Column("config", sa.JSON()),
            sa.Column("description", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("name", name="uq_ai_models_name"),
        )

    if not _table_exists("meetings"):
        op.create_table(
            "meetings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("meeting_id", sa.String(length=64), nullable=False),
            sa.Column("case_ids", sa.JSON()),
            sa.Column("status", sa.String(length=20)),
            sa.Column("moderator_model_id", sa.Integer(), sa.ForeignKey("ai_models.id")),
            sa.Column("analyst_model_ids", sa.JSON()),
            sa.Column("final_report_id", sa.Integer()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("meeting_id", name="uq_meetings_meeting_id"),
        )
        op.create_index("ix_meetings_meeting_id", "meetings", ["meeting_id"])

    if not _table_exists("meeting_conversations"):
        op.create_table(
            "meeting_conversations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("meeting_id", sa.String(length=64), sa.ForeignKey("meetings.meeting_id")),
            sa.Column("round_number", sa.Integer(), nullable=False),
            sa.Column("speaker_model_id", sa.Integer(), sa.ForeignKey("ai_models.id")),
            sa.Column("message_type", sa.String(length=20)),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("extra_data", sa.JSON()),
            sa.Column("parent_message_id", sa.Integer(), sa.ForeignKey("meeting_conversations.id")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_meeting_conversations_meeting_id", "meeting_conversations", ["meeting_id"])

    if not _table_exists("analysis_results"):
        op.create_table(
            "analysis_results",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("meeting_id", sa.String(length=64), sa.ForeignKey("meetings.meeting_id")),
            sa.Column("analyst_model_id", sa.Integer(), sa.ForeignKey("ai_models.id")),
            sa.Column("round_number", sa.Integer(), nullable=False),
            sa.Column("result_content", sa.JSON(), nullable=False),
            sa.Column("version", sa.Integer(), server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_analysis_results_meeting_id", "analysis_results", ["meeting_id"])

    if not _table_exists("evaluations"):
        op.create_table(
            "evaluations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("meeting_id", sa.String(length=64), sa.ForeignKey("meetings.meeting_id")),
            sa.Column("evaluator_model_id", sa.Integer(), sa.ForeignKey("ai_models.id")),
            sa.Column("target_result_id", sa.Integer(), sa.ForeignKey("analysis_results.id")),
            sa.Column("score", sa.Integer()),
            sa.Column("strengths", sa.JSON()),
            sa.Column("weaknesses", sa.JSON()),
            sa.Column("suggestions", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_evaluations_meeting_id", "evaluations", ["meeting_id"])

    if not _table_exists("rankings"):
        op.create_table(
            "rankings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("meeting_id", sa.String(length=64), sa.ForeignKey("meetings.meeting_id")),
            sa.Column("evaluator_model_id", sa.Integer(), sa.ForeignKey("ai_models.id")),
            sa.Column("stage", sa.String(length=20)),
            sa.Column("ranking_data", sa.JSON(), nullable=False),
            sa.Column("aggregated_data", sa.JSON()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_rankings_meeting_id", "rankings", ["meeting_id"])

    if not _table_exists("reports"):
        op.create_table(
            "reports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("meeting_id", sa.String(length=64), sa.ForeignKey("meetings.meeting_id")),
            sa.Column("report_type", sa.String(length=20)),
            sa.Column("content", sa.JSON(), nullable=False),
            sa.Column("consensus_points", sa.JSON()),
            sa.Column("disagreement_points", sa.JSON()),
            sa.Column("model_contributions", sa.JSON()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_reports_meeting_id", "reports", ["meeting_id"])
        if _table_exists("meetings") and not _fk_exists("meetings", "fk_meetings_final_report_id"):
            op.create_foreign_key(
                "fk_meetings_final_report_id",
                "meetings",
                "reports",
                ["final_report_id"],
                ["id"],
            )

    if not _table_exists("preprocess_jobs"):
        op.create_table(
            "preprocess_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id"), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("finished_at", sa.DateTime(timezone=True)),
            sa.Column("error", sa.Text()),
        )
        op.create_index("ix_preprocess_jobs_case_id", "preprocess_jobs", ["case_id"])
        op.create_index("ix_preprocess_jobs_status", "preprocess_jobs", ["status"])

    if not _table_exists("system_configs"):
        op.create_table(
            "system_configs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("config_key", sa.String(length=100), nullable=False),
            sa.Column("config_value", sa.Text()),
            sa.Column("config_type", sa.String(length=50), nullable=False),
            sa.Column("category", sa.String(length=50), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("is_encrypted", sa.String(length=10)),
            sa.Column("extra_data", sa.JSON()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("config_key", name="uq_system_configs_config_key"),
        )
        op.create_index("ix_system_configs_config_key", "system_configs", ["config_key"])

    if not _table_exists("conclusions"):
        op.create_table(
            "conclusions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("case_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20)),
            sa.Column("confidence", sa.Float()),
            sa.Column("risk_level", sa.String(length=20)),
            sa.Column("summary", sa.Text()),
            sa.Column("evidence", sa.JSON()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
        )
        op.create_index("ix_conclusions_case_id", "conclusions", ["case_id"])

    if not _table_exists("conclusion_reviews"):
        op.create_table(
            "conclusion_reviews",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("conclusion_id", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(length=20), nullable=False),
            sa.Column("note", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_conclusion_reviews_conclusion_id", "conclusion_reviews", ["conclusion_id"])

    if not _table_exists("agent_tasks"):
        op.create_table(
            "agent_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("query", sa.Text(), nullable=False),
            sa.Column("case_ids", sa.JSON()),
            sa.Column("status", sa.String(length=20)),
            sa.Column("result", sa.JSON()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
        )


def downgrade() -> None:
    for table in [
        "agent_tasks",
        "conclusion_reviews",
        "conclusions",
        "system_configs",
        "preprocess_jobs",
        "reports",
        "rankings",
        "evaluations",
        "analysis_results",
        "meeting_conversations",
        "meetings",
        "ai_models",
        "cases",
    ]:
        if _table_exists(table):
            op.drop_table(table)
