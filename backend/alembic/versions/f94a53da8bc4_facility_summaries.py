"""Add a rebuildable facility catalog projection; preserve all business tables."""
from alembic import op
import sqlalchemy as sa

revision = 'f94a53da8bc4'
down_revision = 'e83f42c97ab3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('facility_derived_summaries',
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('jurisdiction_assets.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('algorithm_version', sa.String(80), nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_facility_summary_checked', 'facility_derived_summaries', ['checked_at'])


def downgrade():
    raise RuntimeError('restore_compatible_backup_required_for_facility_downgrade')
