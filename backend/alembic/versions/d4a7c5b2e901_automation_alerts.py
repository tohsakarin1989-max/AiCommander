"""automation alerts

Revision ID: d4a7c5b2e901
Revises: c8e34d91a6b2
Create Date: 2026-04-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "d4a7c5b2e901"
down_revision = "c8e34d91a6b2"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return name in _inspector().get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(idx["name"] == index_name for idx in _inspector().get_indexes(table_name))


def _create_index_once(index_name: str, table_name: str, columns: list[str]) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if not _table_exists("automation_alerts"):
        op.create_table(
            "automation_alerts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("alert_number", sa.String(length=50), nullable=False, unique=True),
            sa.Column("source_system", sa.String(length=100), nullable=False, server_default="simulated"),
            sa.Column("alert_type", sa.String(length=50), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("level", sa.String(length=20), nullable=False, server_default="medium"),
            sa.Column("risk_level", sa.String(length=20), nullable=False, server_default="high"),
            sa.Column("occurred_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("location", sa.String(length=200), nullable=True),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("facility_id", sa.String(length=100), nullable=True),
            sa.Column("facility_name", sa.String(length=200), nullable=True),
            sa.Column("parameter_snapshot", sa.JSON(), nullable=True),
            sa.Column("sensing_summary", sa.JSON(), nullable=True),
            sa.Column("ai_assessment", sa.JSON(), nullable=True),
            sa.Column("suggested_actions", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending_review"),
            sa.Column("handling_result", sa.String(length=100), nullable=True),
            sa.Column("review_notes", sa.Text(), nullable=True),
            sa.Column("is_simulated", sa.Boolean(), nullable=True),
            sa.Column("related_event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=True),
            sa.Column("related_case_id", sa.Integer(), sa.ForeignKey("cases.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    _create_index_once("ix_automation_alerts_number", "automation_alerts", ["alert_number"])
    _create_index_once("ix_automation_alerts_status", "automation_alerts", ["status"])
    _create_index_once("ix_automation_alerts_type_time", "automation_alerts", ["alert_type", "occurred_time"])
    _create_index_once("ix_automation_alerts_geo", "automation_alerts", ["latitude", "longitude"])


def downgrade() -> None:
    if _table_exists("automation_alerts"):
        op.drop_table("automation_alerts")
