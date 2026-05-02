"""jurisdiction risk foundation

Revision ID: c8e34d91a6b2
Revises: b7a94f31c2d6
Create Date: 2026-04-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "c8e34d91a6b2"
down_revision = "b7a94f31c2d6"
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


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(col["name"] == column_name for col in _inspector().get_columns(table_name))


def _add_column_once(table_name: str, column: sa.Column) -> None:
    if _table_exists(table_name) and not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def _create_index_once(index_name: str, table_name: str, columns: list[str]) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if not _table_exists("jurisdiction_assets"):
        op.create_table(
            "jurisdiction_assets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("external_id", sa.String(length=200), nullable=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("asset_type", sa.String(length=50), nullable=False),
            sa.Column("geometry_type", sa.String(length=20), nullable=True),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("geometry", sa.JSON(), nullable=True),
            sa.Column("address", sa.String(length=500), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("source", sa.String(length=50), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=True),
            sa.Column("risk_level", sa.Integer(), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=True),
            sa.Column("verified", sa.Boolean(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("tags", sa.JSON(), nullable=True),
            sa.Column("attributes", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    for column in (
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
    ):
        _add_column_once("jurisdiction_assets", column)

    _create_index_once("ix_jurisdiction_assets_type", "jurisdiction_assets", ["asset_type"])
    _create_index_once("ix_jurisdiction_assets_external_id", "jurisdiction_assets", ["external_id"])
    _create_index_once("ix_jurisdiction_assets_source", "jurisdiction_assets", ["source"])
    _create_index_once("ix_jurisdiction_assets_status", "jurisdiction_assets", ["status"])
    _create_index_once("ix_jurisdiction_assets_geo", "jurisdiction_assets", ["latitude", "longitude"])

    if not _table_exists("jurisdiction_feedback"):
        op.create_table(
            "jurisdiction_feedback",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id"), nullable=True),
            sa.Column("asset_id", sa.Integer(), sa.ForeignKey("jurisdiction_assets.id"), nullable=True),
            sa.Column("feedback_type", sa.String(length=50), nullable=False),
            sa.Column("adopted", sa.Boolean(), nullable=True),
            sa.Column("result", sa.Text(), nullable=True),
            sa.Column("effectiveness_score", sa.Float(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("extra", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    _create_index_once("ix_jurisdiction_feedback_case_id", "jurisdiction_feedback", ["case_id"])
    _create_index_once("ix_jurisdiction_feedback_type", "jurisdiction_feedback", ["feedback_type"])
    _create_index_once("ix_jurisdiction_feedback_adopted", "jurisdiction_feedback", ["adopted"])


def downgrade() -> None:
    if _table_exists("jurisdiction_feedback"):
        op.drop_table("jurisdiction_feedback")
    if _table_exists("jurisdiction_assets"):
        op.drop_table("jurisdiction_assets")
