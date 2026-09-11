"""Road authorization and versioned graph catalog; no existing data mutation."""
from alembic import op
import sqlalchemy as sa

revision = '5fa2c86b91f6'
down_revision = '4ef1b75a80e5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('road_access_groups', sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False, unique=True),
        sa.Column('policy_revision', sa.Integer(), nullable=False),
        sa.CheckConstraint('policy_revision > 0', name='ck_road_group_revision'))
    op.create_table('road_access_memberships',
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('road_access_groups.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_until', sa.DateTime(timezone=True)),
        sa.CheckConstraint('valid_until IS NULL OR valid_until > valid_from', name='ck_road_membership_interval'))
    op.create_table('road_access_grants', sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('road_access_groups.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('policy_revision', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), sa.ForeignKey('map_sources.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('feature_id', sa.String(100), nullable=False), sa.Column('decision', sa.String(10), nullable=False),
        sa.Column('evidence_reference', sa.String(500), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('group_id', 'policy_revision', 'source_id', 'feature_id', name='uq_road_grant_version'),
        sa.CheckConstraint("decision IN ('allow', 'deny')", name='ck_road_grant_decision'),
        sa.CheckConstraint('policy_revision > 0', name='ck_road_grant_revision'))
    op.create_index('ix_road_access_grants_group_id', 'road_access_grants', ['group_id'])
    op.create_table('road_network_versions', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('road_access_groups.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('policy_revision', sa.Integer(), nullable=False),
        sa.Column('public_bundle_id', sa.Integer(), sa.ForeignKey('public_map_bundles.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('input_sha256', sa.String(64), nullable=False), sa.Column('conditions_sha256', sa.String(64), nullable=False),
        sa.Column('source_manifest', sa.JSON(), nullable=False), sa.Column('engine_version', sa.String(80), nullable=False),
        sa.Column('builder_version', sa.String(80), nullable=False), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('graph_sha256', sa.String(64)), sa.Column('artifact_key', sa.String(200)),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False), sa.Column('valid_until', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('group_id', 'policy_revision', 'input_sha256', 'conditions_sha256',
            'engine_version', 'builder_version', name='uq_road_network_inputs'),
        sa.CheckConstraint("status IN ('building', 'ready', 'failed', 'retired')", name='ck_road_network_status'),
        sa.CheckConstraint("status != 'ready' OR (graph_sha256 IS NOT NULL AND artifact_key IS NOT NULL)", name='ck_road_network_ready'),
        sa.CheckConstraint('valid_until IS NULL OR valid_until > valid_from', name='ck_road_network_interval'),
        sa.CheckConstraint('policy_revision > 0', name='ck_road_network_revision'))
    op.create_index('ix_road_network_versions_group_id', 'road_network_versions', ['group_id'])


def downgrade():
    # Published references and authorization history must not be discarded by an app rollback.
    raise RuntimeError('restore_compatible_backup_required_for_road_network_downgrade')
