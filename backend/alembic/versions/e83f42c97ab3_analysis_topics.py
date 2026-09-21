"""Saved topical conditions and immutable result revisions; raw records unchanged."""
from alembic import op
import sqlalchemy as sa

revision = 'e83f42c97ab3'
down_revision = 'd72e31b86fa2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('analysis_topics',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('filters', sa.JSON(), nullable=False),
        sa.Column('scope_version', sa.String(64), nullable=False),
        sa.Column('paused', sa.Boolean(), nullable=False),
        sa.Column('refresh_state', sa.String(24), nullable=False),
        sa.Column('lease_token', sa.String(36)),
        sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('next_refresh_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_error', sa.String(80)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_analysis_topics_owner', 'analysis_topics', ['created_by', 'created_at', 'id'])
    op.create_index('ix_analysis_topics_due', 'analysis_topics', ['paused', 'refresh_state', 'next_refresh_at'])
    op.create_table('topic_snapshots',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('topic_id', sa.String(36), sa.ForeignKey('analysis_topics.id', ondelete='CASCADE'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('topic_id', 'revision', name='uq_topic_snapshot_revision'))
    op.create_index('ix_topic_snapshot_history', 'topic_snapshots', ['topic_id', 'revision'])


def downgrade():
    raise RuntimeError('restore_compatible_backup_required_for_topic_downgrade')
