"""Preserve source rows and versioned manual failed-row corrections."""
from alembic import op
import sqlalchemy as sa

revision = "c508d9e0f162"
down_revision = "b4f7c8d9e051"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "case_import_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("case_import_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), sa.ForeignKey("operational_areas.id"), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("source_values", sa.JSON(), nullable=False),
        sa.Column("current_values", sa.JSON(), nullable=False),
        sa.Column("time_zone", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("corrections", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("batch_id", "row_number", name="uq_case_import_rows_source"),
    )
    op.create_index("ix_case_import_rows_batch_id", "case_import_rows", ["batch_id"])
    op.create_index("ix_case_import_rows_operational_area_id", "case_import_rows", ["operational_area_id"])


def downgrade():
    op.drop_index("ix_case_import_rows_operational_area_id", table_name="case_import_rows")
    op.drop_index("ix_case_import_rows_batch_id", table_name="case_import_rows")
    op.drop_table("case_import_rows")
