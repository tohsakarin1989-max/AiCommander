"""Durable case import receipts; no existing case fields are rewritten."""
from alembic import op
import sqlalchemy as sa

revision = "b4f7c8d9e051"
down_revision = "a3e6b7c8d940"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "case_import_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), sa.ForeignKey("operational_areas.id"), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("input_hash", name="uq_case_import_batches_input_hash"),
    )
    op.create_index("ix_case_import_batches_operational_area_id", "case_import_batches", ["operational_area_id"])


def downgrade():
    # Restoring an old application uses its matching backup; do not downgrade a live DB.
    op.drop_index("ix_case_import_batches_operational_area_id", table_name="case_import_batches")
    op.drop_table("case_import_batches")
