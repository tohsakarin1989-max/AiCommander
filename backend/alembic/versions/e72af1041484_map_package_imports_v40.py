"""Durable schema-2 public map reception and resumable chunk receipts."""
from alembic import op
import sqlalchemy as sa

revision = 'e72af1041484'
down_revision = 'd619e0f20373'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('map_package_imports',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('manifest_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('manifest', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('error_code', sa.String(80)),
        sa.Column('report', sa.JSON()),
        sa.Column('lease_token', sa.String(36)),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_map_package_imports_status', 'map_package_imports', ['status'])
    op.create_table('map_package_import_chunks',
        sa.Column('import_id', sa.String(36), sa.ForeignKey('map_package_imports.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('name', sa.String(110), primary_key=True),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False))


def downgrade():
    op.drop_table('map_package_import_chunks')
    op.drop_index('ix_map_package_imports_status', table_name='map_package_imports')
    op.drop_table('map_package_imports')
