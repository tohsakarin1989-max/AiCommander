"""Optional version-bound entrance connection evidence, not passage permission."""
from alembic import op
import sqlalchemy as sa

revision = "4ef1b75a80e5"
down_revision = "3df0a64979d4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("internal_road_reviews", sa.Column("connection_evidence", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("internal_road_reviews") as batch:
        batch.drop_column("connection_evidence")
