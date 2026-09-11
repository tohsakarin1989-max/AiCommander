"""Add immutable case road attachments, preserving original case snapshots."""
from alembic import op
import sqlalchemy as sa

revision = '71c4e08db318'
down_revision = '60b3d97ca207'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('case_road_artifacts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('case_id', sa.Integer(), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('case_result_id', sa.String(36), sa.ForeignKey('case_result_snapshots.id', ondelete='CASCADE'), nullable=False),
        sa.Column('network_id', sa.String(36), sa.ForeignKey('road_network_versions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('operation', sa.String(20), nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('content', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('case_result_id', 'created_by', 'content_sha256', name='uq_case_road_artifact_content'))
    op.create_index('ix_case_road_artifacts_history', 'case_road_artifacts', ['case_result_id', 'created_at', 'id'])


def downgrade():
    raise RuntimeError('restore_compatible_backup_required_for_case_road_artifact_downgrade')
