"""Versioned case result snapshots; no changes to original case records."""
from alembic import op
import sqlalchemy as sa

revision = "09ac731646a1"
down_revision = "f830b2152595"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "case_result_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_profile_id", sa.String(36), sa.ForeignKey("case_analysis_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("case_id", "content_sha256", name="uq_case_result_content"),
    )
    op.create_index("ix_case_results_history", "case_result_snapshots", ["case_id", "created_at", "id"])


def downgrade():
    raise RuntimeError("restore_compatible_backup_required_for_case_results_downgrade")
