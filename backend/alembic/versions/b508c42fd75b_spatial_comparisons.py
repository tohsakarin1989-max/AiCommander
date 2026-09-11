"""Persist frozen spatial coverage comparisons separately from business facts."""
from alembic import op
import sqlalchemy as sa

revision = 'b508c42fd75b'
down_revision = 'a4f7b31ec64a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('spatial_coverage_comparisons',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('operational_area_id', sa.Integer(), sa.ForeignKey('operational_areas.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_spatial_coverage_comparisons_operational_area_id', 'spatial_coverage_comparisons', ['operational_area_id'])


def downgrade():
    raise RuntimeError('restore_compatible_backup_required_for_spatial_comparison_downgrade')
