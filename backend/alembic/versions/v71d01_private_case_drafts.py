"""Private expiring case drafts and source-bound preprocessing supplements.

Revision ID: v71d01
Revises: v70s01
"""
from alembic import op
import sqlalchemy as sa

revision = "v71d01"
down_revision = "v70s01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "case_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), sa.ForeignKey("operational_areas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("target_case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="SET NULL")),
        sa.Column("base_case_revision", sa.Integer()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("form_snapshot", sa.JSON(), nullable=False),
        sa.Column("last_save_sha256", sa.String(64), nullable=False),
        sa.Column("submission_key", sa.String(128), nullable=False),
        sa.Column("submission_sha256", sa.String(64)),
        sa.Column("submitted_case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','submitted')", name="ck_case_draft_status"),
        sa.CheckConstraint("mode IN ('create','edit')", name="ck_case_draft_mode"),
    )
    op.create_index("ix_case_drafts_owner_expiry", "case_drafts", ["owner_id", "expires_at"])
    op.create_index("ix_case_drafts_expires_at", "case_drafts", ["expires_at"])
    op.create_table(
        "case_preprocess_supplements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_profile_id", sa.String(36), sa.ForeignKey("case_analysis_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_revision_id", sa.Integer(), sa.ForeignKey("case_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_fingerprint", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("case_profile_id", "model_fingerprint", name="uq_case_preprocess_supplement_input"),
    )
    op.create_index("ix_case_preprocess_supplements_case_id", "case_preprocess_supplements", ["case_id"])


def downgrade():
    # Do not silently erase private work or preserved independent business output.
    for table in ("case_drafts", "case_preprocess_supplements"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(f"{table}_require_backup_before_downgrade")
    op.drop_table("case_preprocess_supplements")
    op.drop_table("case_drafts")
