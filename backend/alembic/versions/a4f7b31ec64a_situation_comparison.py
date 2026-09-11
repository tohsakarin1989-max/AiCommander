"""Keep equal-window comparison inputs with each new situation brief."""
from alembic import op
import sqlalchemy as sa

revision = 'a4f7b31ec64a'
down_revision = '93e6a20fd53b'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('situation_briefs', sa.Column('comparison_snapshot', sa.JSON(), nullable=True))


def downgrade():
    raise RuntimeError('restore_compatible_backup_required_for_situation_downgrade')
