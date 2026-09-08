"""knowledge asset lifecycle

Revision ID: f6c8d2e4a913
Revises: e4b5c6d7a812
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6c8d2e4a913"
down_revision: Union[str, None] = "e4b5c6d7a812"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_type", sa.String(length=30), nullable=False),
        sa.Column("source_case_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("source_signature", sa.String(length=64), nullable=False),
        sa.Column("source_data_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("generated_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewer_label", sa.String(length=100), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["generated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_type",
            "source_case_id",
            "version",
            name="uq_knowledge_asset_case_version",
        ),
    )
    op.create_index("ix_knowledge_assets_id", "knowledge_assets", ["id"], unique=False)
    op.create_index(
        "ix_knowledge_assets_case_type",
        "knowledge_assets",
        ["source_case_id", "asset_type"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_assets_type_status",
        "knowledge_assets",
        ["asset_type", "status"],
        unique=False,
    )

    op.create_table(
        "knowledge_reuse_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_asset_id", sa.Integer(), nullable=False),
        sa.Column("target_case_id", sa.Integer(), nullable=False),
        sa.Column("target_asset_id", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("purpose", sa.String(length=200), nullable=False),
        sa.Column("applicability", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["knowledge_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_asset_id"], ["knowledge_assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_knowledge_reuse_idempotency"),
    )
    op.create_index("ix_knowledge_reuse_records_id", "knowledge_reuse_records", ["id"], unique=False)
    op.create_index(
        "ix_knowledge_reuse_target_created",
        "knowledge_reuse_records",
        ["target_case_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_reuse_source_created",
        "knowledge_reuse_records",
        ["source_asset_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_reuse_source_created", table_name="knowledge_reuse_records")
    op.drop_index("ix_knowledge_reuse_target_created", table_name="knowledge_reuse_records")
    op.drop_index("ix_knowledge_reuse_records_id", table_name="knowledge_reuse_records")
    op.drop_table("knowledge_reuse_records")
    op.drop_index("ix_knowledge_assets_type_status", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_case_type", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_id", table_name="knowledge_assets")
    op.drop_table("knowledge_assets")
