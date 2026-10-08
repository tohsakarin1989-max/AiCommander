"""Record explicit feedback provenance without rewriting historical facts."""
from alembic import op
import sqlalchemy as sa

revision = "v80f01"
down_revision = "v75r01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cases", sa.Column("feedback_known_fields", sa.JSON(), nullable=True))


def downgrade():
    # A v8 yes/no has different source semantics from a legacy default. Dropping
    # this provenance would silently remove that distinction from business data.
    if op.get_bind().execute(sa.text(
            "SELECT 1 FROM cases WHERE feedback_known_fields IS NOT NULL "
            "AND CAST(feedback_known_fields AS TEXT) <> 'null' LIMIT 1")).first():
        raise RuntimeError("feedback_provenance_requires_compatible_backup_before_downgrade")
    with op.batch_alter_table("cases") as batch:
        batch.drop_column("feedback_known_fields")
