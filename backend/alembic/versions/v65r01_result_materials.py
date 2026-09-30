"""Unified typed materials and version-bound decisions; preserve original records.

Revision ID: v65r01
Revises: v64t01
"""
from alembic import op
import sqlalchemy as sa

revision = 'v65r01'
down_revision = 'v64t01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('facility_materials',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('jurisdiction_assets.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('title', sa.String(240), nullable=False),
        sa.Column('idempotency_key', sa.String(80), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('source_manifest', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('created_by', 'idempotency_key', name='uq_facility_material_request'))
    op.create_table('result_judgments',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('result_kind', sa.String(24), nullable=False),
        sa.Column('result_id', sa.String(80), nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('decision', sa.String(40), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('additional_sources', sa.JSON(), nullable=False),
        sa.Column('idempotency_key', sa.String(80), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('created_by', 'idempotency_key', name='uq_result_judgment_request'))
    op.create_index('ix_result_judgment_version', 'result_judgments', ['result_kind', 'result_id', 'content_sha256'])
    op.create_table('meeting_frozen_inputs',
        sa.Column('meeting_id', sa.String(64), sa.ForeignKey('meetings.meeting_id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade():
    # Do not drop human decisions or captured materials as a side effect of rollback.
    connection = op.get_bind()
    for name in ('result_judgments', 'facility_materials', 'meeting_frozen_inputs'):
        if connection.execute(sa.text(f'SELECT 1 FROM {name} LIMIT 1')).first():
            raise RuntimeError('v65_materials_require_backup_before_downgrade')
    op.drop_table('meeting_frozen_inputs')
    op.drop_table('result_judgments')
    op.drop_table('facility_materials')
