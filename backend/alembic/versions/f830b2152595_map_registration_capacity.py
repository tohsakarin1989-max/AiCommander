"""Match schema-2 transport limits without truncating public map metadata."""
from alembic import op
import sqlalchemy as sa

revision = 'f830b2152595'
down_revision = 'e72af1041484'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite already stores 64-bit integers and does not enforce VARCHAR length.
    if op.get_bind().dialect.name == 'sqlite':
        return
    with op.batch_alter_table('public_map_bundles') as batch:
        for name, length in [('provider', 100), ('source_version', 100), ('license_record', 200)]:
            batch.alter_column(name, existing_type=sa.String(length), type_=sa.String(512))
    with op.batch_alter_table('map_snapshots') as batch:
        batch.alter_column('version', existing_type=sa.String(200), type_=sa.String(1024))
    with op.batch_alter_table('map_package_artifacts') as batch:
        batch.alter_column('size_bytes', existing_type=sa.Integer(), type_=sa.BigInteger())


def downgrade():
    # Preserve wider values. Older app deployment requires its compatible backup;
    # schema rollback must never truncate imported source metadata or asset sizes.
    raise RuntimeError('restore_compatible_backup_required_for_map_capacity_downgrade')
