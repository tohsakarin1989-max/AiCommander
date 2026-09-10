"""Scoped immutable case import configuration templates."""
from alembic import op
import sqlalchemy as sa

revision = "d619e0f20373"
down_revision = "c508d9e0f162"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "case_import_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("operational_area_id", sa.Integer(), sa.ForeignKey("operational_areas.id"), nullable=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_case_import_templates_operational_area_id", "case_import_templates", ["operational_area_id"])


def downgrade():
    op.drop_index("ix_case_import_templates_operational_area_id", table_name="case_import_templates")
    op.drop_table("case_import_templates")
