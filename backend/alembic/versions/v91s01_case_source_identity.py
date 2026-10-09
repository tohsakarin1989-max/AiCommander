"""Preserve source row identity and adopted field provenance, without rewriting facts."""
from alembic import op
import sqlalchemy as sa

revision = 'v91s01'
down_revision = 'v80f01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('case_import_source_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('operational_area_id', sa.Integer(), sa.ForeignKey('operational_areas.id'), nullable=False),
        sa.Column('source_key', sa.String(80), nullable=False),
        sa.Column('external_key', sa.String(160), nullable=False),
        sa.Column('case_id', sa.Integer(), sa.ForeignKey('cases.id', ondelete='SET NULL')),
        sa.Column('source_version', sa.String(100)), sa.Column('source_hash', sa.String(64), nullable=False),
        sa.Column('source_values', sa.JSON(), nullable=False), sa.Column('adopted_values', sa.JSON(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('last_batch_id', sa.String(36), sa.ForeignKey('case_import_batches.id'), nullable=False),
        sa.Column('last_row_number', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('operational_area_id', 'source_key', 'external_key', name='uq_case_import_source_identity'))
    op.create_index('ix_case_import_source_records_operational_area_id', 'case_import_source_records', ['operational_area_id'])
    op.create_index('ix_case_import_source_records_case_id', 'case_import_source_records', ['case_id'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT 1 FROM case_import_source_records LIMIT 1')).first():
        raise RuntimeError('source_identity_requires_compatible_backup_before_downgrade')
    op.drop_table('case_import_source_records')
