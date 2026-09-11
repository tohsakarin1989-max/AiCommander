"""Add optional vehicle road conditions without deriving mass from oil volume."""
from alembic import op
import sqlalchemy as sa

revision = '82d5f19ec429'
down_revision = '71c4e08db318'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('case_vehicles', sa.Column('road_vehicle_kind', sa.String(10), nullable=True))
    op.add_column('case_vehicles', sa.Column('height_m', sa.Float(), nullable=True))
    op.add_column('case_vehicles', sa.Column('gross_weight_t', sa.Float(), nullable=True))


def downgrade():
    raise RuntimeError('restore_compatible_backup_required_for_vehicle_conditions_downgrade')
