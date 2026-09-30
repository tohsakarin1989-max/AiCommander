"""Continuing questions, immutable definitions and durable aggregation chunks."""
from alembic import op
import sqlalchemy as sa

revision = 'v64t01'
down_revision = 'v63h01'
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column('question', sa.Text(), nullable=False, server_default=''),
        sa.Column('question_kind', sa.String(40), nullable=False, server_default='condition_changes'),
        sa.Column('window', sa.JSON(), nullable=False, server_default='{"mode":"fixed"}'),
        sa.Column('source_context', sa.JSON()),
        sa.Column('definition_revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('requested_generation', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_data_revision', sa.Integer(), nullable=False, server_default='-1'),
        sa.Column('latest_job_id', sa.String(36)),
    ):
        op.add_column('analysis_topics', column)
    from app.models.analysis_topic import (TopicDefinitionRevision, TopicDependency,
                                          TopicDataRevision, TopicRefreshChunk)
    bind = op.get_bind()
    for model in (TopicDefinitionRevision, TopicDependency, TopicDataRevision, TopicRefreshChunk):
        model.__table__.create(bind, checkfirst=True)
    from uuid import uuid4
    import json
    rows = bind.execute(sa.text('SELECT id, title, filters FROM analysis_topics')).mappings()
    for row in rows:
        filters = json.loads(row['filters']) if isinstance(row['filters'], str) else row['filters']
        bind.execute(TopicDefinitionRevision.__table__.insert().values(id=str(uuid4()), topic_id=row['id'],
            revision=1, payload={'revision': 1, 'title': row['title'], 'question': row['title'],
            'question_kind': 'condition_changes', 'filters': filters, 'window': {'mode': 'fixed'},
            'source_context': None}))
    from app.services.topic_revision_fence import install
    install(bind)


def downgrade():
    # Questions/condition edits are user input. Dropping them is not a safe
    # rollback. Restore a compatible backup into a separate target instead.
    raise RuntimeError('restore_compatible_backup_required_for_topic_v64')
