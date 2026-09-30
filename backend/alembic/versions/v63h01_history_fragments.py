"""Persistent source fragments and independent retrieval postings.

Revision ID: v63h01
Revises: v62f01
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR

revision = 'v63h01'
down_revision = 'v62f01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('case_history_fragments',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('source_type', sa.String(40), nullable=False),
        sa.Column('source_id', sa.String(64), nullable=False),
        sa.Column('source_hash', sa.String(64), nullable=False),
        sa.Column('source_revision_id', sa.Integer(), sa.ForeignKey('case_revisions.id', ondelete='CASCADE')),
        sa.Column('rule_version', sa.String(120), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('field', sa.String(80), nullable=False),
        sa.Column('field_hash', sa.String(64), nullable=False),
        sa.Column('start', sa.Integer(), nullable=False),
        sa.Column('end', sa.Integer(), nullable=False),
        sa.Column('quote', sa.Text(), nullable=False),
        sa.Column('conditions', sa.JSON(), nullable=False),
        sa.Column('process_event_id', sa.String(64)),
        sa.Column('embedding', VECTOR().with_variant(sa.JSON(), 'sqlite')),
        sa.Column('model_version', sa.String(100)),
        sa.Column('dimension', sa.Integer()),
        sa.Column('embedding_state', sa.String(30), nullable=False),
        sa.ForeignKeyConstraint(['case_id', 'source_type', 'source_id'],
            ['case_history_indexes.case_id', 'case_history_indexes.source_type', 'case_history_indexes.source_id'], ondelete='CASCADE'))
    op.create_index('ix_case_history_fragments_case_id', 'case_history_fragments', ['case_id'])
    op.create_index('ix_history_fragment_parent', 'case_history_fragments', ['case_id', 'source_type', 'source_id'])
    op.create_table('case_history_postings',
        sa.Column('fragment_id', sa.String(64), sa.ForeignKey('case_history_fragments.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('branch', sa.String(20), primary_key=True),
        sa.Column('term', sa.String(640), primary_key=True),
        sa.Column('case_id', sa.Integer(), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False))
    op.create_index('ix_case_history_postings_case_id', 'case_history_postings', ['case_id'])
    op.create_index('ix_history_posting_lookup', 'case_history_postings', ['branch', 'term', 'fragment_id'])


def downgrade():
    op.drop_table('case_history_postings')
    op.drop_table('case_history_fragments')
