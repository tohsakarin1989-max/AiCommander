"""Append-only road source verification records."""
from alembic import op
import sqlalchemy as sa

revision = "2cef953868c3"
down_revision = "1bde842757b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "internal_road_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("internal_road_imports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), sa.ForeignKey("operational_areas.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("feature_id", sa.String(100), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(80), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("note", sa.String(2000), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("import_id", "feature_id", "sequence", name="uq_road_review_sequence"),
        sa.UniqueConstraint("import_id", "feature_id", "request_key", name="uq_road_review_request"),
    )
    op.create_index("ix_internal_road_reviews_import_id", "internal_road_reviews", ["import_id"])
    op.create_index("ix_internal_road_reviews_operational_area_id", "internal_road_reviews", ["operational_area_id"])


def downgrade():
    op.drop_table("internal_road_reviews")
