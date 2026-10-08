"""Disposable exact-input vector reuse; source revisions remain in their stores."""
from alembic import op
from pgvector.sqlalchemy import VECTOR
import sqlalchemy as sa

revision = 'v75h01'
down_revision = 'v74c01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('case_history_vector_reuse',
        sa.Column('text_sha256', sa.String(64), primary_key=True),
        sa.Column('encoder_fingerprint', sa.String(64), primary_key=True),
        sa.Column('dimension', sa.Integer(), primary_key=True),
        sa.Column('model_version', sa.String(100), nullable=False),
        sa.Column('embedding', VECTOR().with_variant(sa.JSON(), 'sqlite'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade():
    # No source text, revisions, events or user decisions are removed.
    op.drop_table('case_history_vector_reuse')
