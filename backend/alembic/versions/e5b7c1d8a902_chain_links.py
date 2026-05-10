"""chain links

Revision ID: e5b7c1d8a902
Revises: d4a7c5b2e901
Create Date: 2026-05-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
import json


revision = "e5b7c1d8a902"
down_revision = "d4a7c5b2e901"
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


def _config_exists(key: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT COUNT(1) FROM system_configs WHERE config_key = :key"), {"key": key}).scalar()
    return bool(rows)


def _insert_config(key: str, value: str, description: str, extra_data: dict) -> None:
    if _table_exists("system_configs") and not _config_exists(key):
        op.get_bind().execute(
            sa.text(
                """
                INSERT INTO system_configs
                    (config_key, config_value, config_type, category, description, is_encrypted, extra_data)
                VALUES
                    (:key, :value, 'number', 'chain_analysis', :description, 'false', :extra_data)
                """
            ),
            {
                "key": key,
                "value": value,
                "description": description,
                "extra_data": json.dumps(extra_data, ensure_ascii=False),
            },
        )


def upgrade() -> None:
    if not _table_exists("chain_links"):
        op.create_table(
            "chain_links",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("case_id_a", sa.Integer(), sa.ForeignKey("cases.id"), nullable=False),
            sa.Column("case_id_b", sa.Integer(), sa.ForeignKey("cases.id"), nullable=False),
            sa.Column("link_type", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="inferred"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("distance_km", sa.Float(), nullable=False, server_default="0"),
            sa.Column("time_diff_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reasoning", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confirmed_by", sa.String(length=100), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("case_id_a", "case_id_b", "link_type", name="uq_chain_links_pair_type"),
        )

    _create_index_once("ix_chain_links_case_a", "chain_links", ["case_id_a"])
    _create_index_once("ix_chain_links_case_b", "chain_links", ["case_id_b"])
    _create_index_once("ix_chain_links_status", "chain_links", ["status"])
    _create_index_once("ix_chain_links_type_status", "chain_links", ["link_type", "status"])

    _insert_config("chain_radius_km", "20", "链条推断空间搜索半径（公里）", {"min": 1, "max": 100})
    _insert_config("chain_time_window_days", "180", "链条推断时间窗口（天）", {"min": 1, "max": 730})
    _insert_config("chain_min_confidence", "0.3", "链条推断最低展示置信度", {"min": 0, "max": 1})


def downgrade() -> None:
    if _table_exists("chain_links"):
        op.drop_table("chain_links")
