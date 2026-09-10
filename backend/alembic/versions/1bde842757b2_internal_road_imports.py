"""Versioned internal road source imports, independent of map points."""
from alembic import op
import sqlalchemy as sa

revision = "1bde842757b2"
down_revision = "09ac731646a1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "internal_road_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("map_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), sa.ForeignKey("operational_areas.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(80), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", "input_sha256", name="uq_internal_road_source_hash"),
    )
    op.create_index("ix_internal_road_imports_source_id", "internal_road_imports", ["source_id"])
    op.create_index("ix_internal_road_imports_operational_area_id", "internal_road_imports", ["operational_area_id"])


def downgrade():
    op.drop_table("internal_road_imports")
