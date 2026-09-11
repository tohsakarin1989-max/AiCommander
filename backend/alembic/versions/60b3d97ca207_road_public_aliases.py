"""Version-bound internal/public correspondence, without modifying source facts."""
from alembic import op
import sqlalchemy as sa

revision = '60b3d97ca207'
down_revision = '5fa2c86b91f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('road_public_aliases',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('import_id', sa.Integer(), sa.ForeignKey('internal_road_imports.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('feature_id', sa.String(100), nullable=False),
        sa.Column('operational_area_id', sa.Integer(), sa.ForeignKey('operational_areas.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('public_source_sha256', sa.String(64), nullable=False),
        sa.Column('osm_way_id', sa.BigInteger(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('decision', sa.String(20), nullable=False),
        sa.Column('request_key', sa.String(80), nullable=False),
        sa.Column('evidence_reference', sa.String(500), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('import_id', 'feature_id', 'public_source_sha256', 'osm_way_id', 'sequence', name='uq_road_public_alias_sequence'),
        sa.UniqueConstraint('import_id', 'request_key', name='uq_road_public_alias_request'),
        sa.CheckConstraint("decision IN ('verified', 'revoked')", name='ck_road_public_alias_decision'),
        sa.CheckConstraint('osm_way_id > 0 AND sequence > 0', name='ck_road_public_alias_positive'))
    op.create_index('ix_road_public_aliases_operational_area_id', 'road_public_aliases', ['operational_area_id'])


def downgrade():
    raise RuntimeError('restore_compatible_backup_required_for_road_alias_downgrade')
