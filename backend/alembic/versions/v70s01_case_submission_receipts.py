"""Private transactional receipts for retry-safe case creation.

Revision ID: v70s01
Revises: v65r01
"""
from alembic import op
import sqlalchemy as sa

revision = "v70s01"
down_revision = "v65r01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "case_submission_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_case_submission_user_key"),
    )
    op.create_index("ix_case_submission_receipts_case_id", "case_submission_receipts", ["case_id"])


def downgrade():
    # Discarding receipts enables duplicate creation when a client retries.
    if op.get_bind().execute(sa.text("SELECT 1 FROM case_submission_receipts LIMIT 1")).first():
        raise RuntimeError("case_submission_receipts_require_backup_before_downgrade")
    op.drop_table("case_submission_receipts")
