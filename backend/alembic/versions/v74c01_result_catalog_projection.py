"""Rebuildable material metadata and reverse references; no business backfill."""
from alembic import op
import sqlalchemy as sa

revision = 'v74c01'
down_revision = 'v74n01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('result_catalog_projections',
        sa.Column('material_kind', sa.String(24), primary_key=True),
        sa.Column('material_id', sa.String(80), primary_key=True),
        sa.Column('title', sa.String(240), nullable=True),
        sa.Column('material_created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('subject_kind', sa.String(24), nullable=True),
        sa.Column('subject_id', sa.String(80), nullable=True),
        sa.Column('content_sha256', sa.String(64), nullable=True),
        sa.Column('schema_version', sa.String(80), nullable=True),
        sa.Column('algorithm_version', sa.String(80), nullable=False),
        sa.Column('source_sha256', sa.String(64), nullable=True),
        sa.Column('state', sa.String(24), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_result_catalog_checked', 'result_catalog_projections',
                    ['checked_at', 'material_kind', 'material_id'])
    op.create_index('ix_result_catalog_subject', 'result_catalog_projections',
                    ['subject_kind', 'subject_id', 'material_created_at'])
    op.create_table('result_catalog_references',
        sa.Column('material_kind', sa.String(24), primary_key=True),
        sa.Column('material_id', sa.String(80), primary_key=True),
        sa.Column('reference_kind', sa.String(32), primary_key=True),
        sa.Column('reference_id', sa.String(120), primary_key=True),
        sa.Column('relation', sa.String(80), primary_key=True),
        sa.Column('expected_version', sa.String(128), primary_key=True),
        sa.ForeignKeyConstraint(['material_kind', 'material_id'],
                                ['result_catalog_projections.material_kind', 'result_catalog_projections.material_id'],
                                ondelete='CASCADE'))
    op.create_index('ix_result_catalog_reference', 'result_catalog_references', ['reference_kind', 'reference_id'])


def downgrade():
    # These tables contain no user decisions or original materials; rebuildable.
    op.drop_table('result_catalog_references')
    op.drop_table('result_catalog_projections')
