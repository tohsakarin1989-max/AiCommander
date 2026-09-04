"""well risk observations

Revision ID: a2f6c1d9e403
Revises: f7d2a9c4b610
Create Date: 2026-08-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a2f6c1d9e403"
down_revision = "f7d2a9c4b610"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _column_exists(table_name: str, column_name: str) -> bool:
    if table_name not in _inspector().get_table_names():
        return False
    return any(column["name"] == column_name for column in _inspector().get_columns(table_name))


def _add_column_once(table_name: str, column: sa.Column) -> None:
    if not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def upgrade() -> None:
    _add_column_once("events", sa.Column("related_asset_id", sa.Integer(), nullable=True))
    _add_column_once("events", sa.Column("observation_type", sa.String(length=50), nullable=True))
    _add_column_once("events", sa.Column("severity", sa.Integer(), nullable=True))
    _add_column_once("events", sa.Column("freshness", sa.String(length=20), nullable=True))
    _add_column_once("events", sa.Column("confidence_score", sa.Float(), nullable=True))
    _add_column_once("events", sa.Column("review_status", sa.String(length=30), nullable=True))
    _add_column_once("events", sa.Column("evidence_files", sa.JSON(), nullable=True))
    _add_column_once("events", sa.Column("observation_details", sa.JSON(), nullable=True))

    indexes = {item["name"] for item in _inspector().get_indexes("events")}
    if "ix_events_related_asset_id" not in indexes:
        op.create_index("ix_events_related_asset_id", "events", ["related_asset_id"])
    if "ix_events_observation_type" not in indexes:
        op.create_index("ix_events_observation_type", "events", ["observation_type"])


def downgrade() -> None:
    indexes = {item["name"] for item in _inspector().get_indexes("events")}
    if "ix_events_observation_type" in indexes:
        op.drop_index("ix_events_observation_type", table_name="events")
    if "ix_events_related_asset_id" in indexes:
        op.drop_index("ix_events_related_asset_id", table_name="events")
    for column_name in [
        "observation_details",
        "evidence_files",
        "review_status",
        "confidence_score",
        "freshness",
        "severity",
        "observation_type",
        "related_asset_id",
    ]:
        if _column_exists("events", column_name):
            op.drop_column("events", column_name)
