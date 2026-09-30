"""Bind derived chain candidates to both source versions; retain old reviews."""
from alembic import op
import sqlalchemy as sa

revision = "v60c01"
down_revision = "f94a53da8bc4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chain_links", sa.Column("source_hash_a", sa.String(64), nullable=True))
    op.add_column("chain_links", sa.Column("source_hash_b", sa.String(64), nullable=True))
    op.add_column("chain_links", sa.Column("algorithm_version", sa.String(40), nullable=True))


def downgrade():
    raise RuntimeError("restore_compatible_backup_required_for_chain_version_downgrade")
