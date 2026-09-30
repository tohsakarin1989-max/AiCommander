"""Evidence-bound manual facility relationships; never infer from proximity."""
from alembic import op
import sqlalchemy as sa

revision = "v62f01"
down_revision = "v62i01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("case_facility_associations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("jurisdiction_assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_reference_id", sa.Integer(), sa.ForeignKey("source_references.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_revision_id", sa.Integer(), sa.ForeignKey("case_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_type", sa.String(30), nullable=False),
        sa.Column("note", sa.Text(), nullable=False), sa.Column("request_key", sa.String(80), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("revoke_note", sa.Text()),
        sa.UniqueConstraint("case_id", "request_key", name="uq_case_facility_request"))
    op.create_index("ix_case_facility_associations_case_id", "case_facility_associations", ["case_id"])
    op.create_index("ix_case_facility_associations_asset_id", "case_facility_associations", ["asset_id"])


def downgrade():
    raise RuntimeError("restore_compatible_backup_required_for_manual_associations")
