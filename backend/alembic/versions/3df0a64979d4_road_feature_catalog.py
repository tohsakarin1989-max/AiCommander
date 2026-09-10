"""Index each immutable source feature for cross-import lookup."""
from alembic import op
import sqlalchemy as sa

revision = "3df0a64979d4"
down_revision = "2cef953868c3"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table(
        "internal_road_feature_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("internal_road_imports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("map_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), sa.ForeignKey("operational_areas.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("feature_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.UniqueConstraint("import_id", "feature_id", name="uq_internal_road_feature_version"),
    )
    for column in ("import_id", "source_id", "operational_area_id", "feature_id"):
        op.create_index(f"ix_internal_road_feature_versions_{column}", table.name, [column])
    source = sa.table("internal_road_imports", sa.column("id"), sa.column("source_id"),
                      sa.column("operational_area_id"), sa.column("features", sa.JSON()))
    connection = op.get_bind()
    last_id = 0
    while True:
        rows = connection.execute(sa.select(source).where(source.c.id > last_id).order_by(source.c.id).limit(50)).mappings().all()
        if not rows:
            break
        for row in rows:
            values = [{"import_id": row["id"], "source_id": row["source_id"],
                       "operational_area_id": row["operational_area_id"], "feature_id": item["id"],
                       "name": item["properties"]["name"], "kind": item["properties"]["kind"]}
                      for item in row["features"]]
            if values:
                connection.execute(table.insert(), values)
        last_id = rows[-1]["id"]


def downgrade():
    op.drop_table("internal_road_feature_versions")
