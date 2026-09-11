"""Track scope changes independently from normal catalog additions."""
from alembic import op
import sqlalchemy as sa

revision = '93e6a20fd53b'
down_revision = '82d5f19ec429'
branch_labels = None
depends_on = None


def upgrade():
    from app.models.query_scope_revision import install_scope_revision_v1
    op.create_table('query_scope_revision', sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('revision', sa.BigInteger(), nullable=False),
        sa.CheckConstraint('id = 1', name='ck_query_scope_singleton'))
    install_scope_revision_v1(op.get_bind())


def downgrade():
    raise RuntimeError('restore_compatible_backup_required_for_query_scope_downgrade')
