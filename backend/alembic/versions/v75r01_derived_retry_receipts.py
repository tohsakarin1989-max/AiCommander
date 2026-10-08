"""Unique explicit retry receipts without changing other audit records."""
from alembic import op
import sqlalchemy as sa

revision = 'v75r01'
down_revision = 'v75h01'
branch_labels = None
depends_on = None


def upgrade():
    condition = sa.text("action = 'derived_task.explicit_retry'")
    op.create_index('uq_derived_retry_request', 'audit_logs', ['user_id', 'request_id'], unique=True,
                    sqlite_where=condition, postgresql_where=condition)


def downgrade():
    # Dropping a guard while receipts exist would re-enable duplicate requests.
    if op.get_bind().execute(sa.text(
            "SELECT 1 FROM audit_logs WHERE action = 'derived_task.explicit_retry' LIMIT 1")).first():
        raise RuntimeError('derived_retry_receipts_require_compatible_backup_before_downgrade')
    op.drop_index('uq_derived_retry_request', table_name='audit_logs')
