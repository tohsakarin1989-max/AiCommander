"""Add rebuildable historical lexical indexes and resumable backfill cursor."""
from alembic import op
import sqlalchemy as sa

revision = "c61d20a75e91"
down_revision = "b508c42fd75b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "case_history_indexes",
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_type", sa.String(40), primary_key=True),
        sa.Column("source_id", sa.String(64), primary_key=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("rule_version", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "case_history_index_cursors",
        sa.Column("name", sa.String(40), primary_key=True),
        sa.Column("after_case_id", sa.Integer(), nullable=False),
        sa.Column("completed_passes", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    # 只删除可重建派生索引，不删除案件、经验或画像；须先停止对应后台任务。
    op.drop_table("case_history_index_cursors")
    op.drop_table("case_history_indexes")
