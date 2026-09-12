"""Native PostgreSQL vector storage sharing the historical source index."""
from alembic import op
from pgvector.sqlalchemy import VECTOR
import sqlalchemy as sa

revision = 'd72e31b86fa2'
down_revision = 'c61d20a75e91'
branch_labels = None
depends_on = None


def upgrade():
    dialect = op.get_bind().dialect.name
    if dialect == 'postgresql':
        if not op.get_bind().execute(sa.text("SELECT 1 FROM pg_available_extensions WHERE name='vector'")).scalar():
            raise RuntimeError('v5.1 requires a PostgreSQL image containing both PostGIS and pgvector')
        op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.create_table('case_history_embeddings',
        sa.Column('case_id', sa.Integer(), primary_key=True),
        sa.Column('source_type', sa.String(40), primary_key=True),
        sa.Column('source_id', sa.String(64), primary_key=True),
        sa.Column('model_version', sa.String(100), primary_key=True),
        sa.Column('source_hash', sa.String(64), nullable=False),
        sa.Column('dimension', sa.Integer(), nullable=False),
        sa.Column('embedding', VECTOR() if dialect == 'postgresql' else sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['case_id', 'source_type', 'source_id'],
            ['case_history_indexes.case_id', 'case_history_indexes.source_type', 'case_history_indexes.source_id'],
            ondelete='CASCADE'))
    if dialect == 'postgresql':
        op.create_check_constraint('ck_history_embedding_dimension', 'case_history_embeddings',
            'dimension BETWEEN 1 AND 4096 AND vector_dims(embedding) = dimension')


def downgrade():
    # Stop embedding workers first. Business data and shared vector extension remain.
    op.drop_table('case_history_embeddings')
