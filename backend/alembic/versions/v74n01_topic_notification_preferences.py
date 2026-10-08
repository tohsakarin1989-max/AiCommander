"""Independent in-app topic preferences and exact-version dismissals.

Revision ID: v74n01
Revises: v72m01
"""
from alembic import op
import sqlalchemy as sa

revision = 'v74n01'
down_revision = 'v72m01'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('analysis_topics', sa.Column('notification_policy', sa.String(24),
        sa.CheckConstraint("notification_policy IN ('meaningful', 'muted')", name='ck_topic_notification_policy'),
        nullable=False, server_default='meaningful'))
    op.create_table('topic_change_dismissals',
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('snapshot_id', sa.String(36), sa.ForeignKey('topic_snapshots.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade():
    connection = op.get_bind()
    if (connection.execute(sa.text('SELECT 1 FROM topic_change_dismissals LIMIT 1')).first()
            or connection.execute(sa.text("SELECT 1 FROM analysis_topics WHERE notification_policy <> 'meaningful' LIMIT 1")).first()):
        raise RuntimeError('v74_notification_preferences_require_compatible_backup_before_downgrade')
    op.drop_table('topic_change_dismissals')
    op.drop_column('analysis_topics', 'notification_policy')
