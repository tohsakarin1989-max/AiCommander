"""offline maps v3.2

Revision ID: c9a2d3e4f506
Revises: b8f1c2d3e405
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9a2d3e4f506"
down_revision: Union[str, None] = "b8f1c2d3e405"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "public_map_bundles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bundle_id", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("source_version", sa.String(length=100), nullable=False),
        sa.Column("license_record", sa.String(length=200), nullable=False),
        sa.Column("bounds", sa.JSON(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("package_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("imported_by", sa.Integer(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["imported_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bundle_id"),
        sa.UniqueConstraint("package_hash"),
    )
    op.create_index("ix_public_map_bundles_bundle_id", "public_map_bundles", ["bundle_id"], unique=True)
    op.create_index("ix_public_map_bundles_id", "public_map_bundles", ["id"], unique=False)
    op.create_index("ix_public_map_bundles_status", "public_map_bundles", ["status"], unique=False)

    op.create_table(
        "map_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.String(length=200), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), nullable=False),
        sa.Column("public_bundle_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("feature_watermark", sa.String(length=100), nullable=False),
        sa.Column("built_by", sa.Integer(), nullable=True),
        sa.Column("built_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["built_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["operational_area_id"], ["operational_areas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["public_bundle_id"], ["public_map_bundles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version"),
    )
    op.create_index("ix_map_snapshots_area_status", "map_snapshots", ["operational_area_id", "status"], unique=False)
    op.create_index("ix_map_snapshots_version", "map_snapshots", ["version"], unique=True)
    op.create_index(
        "uq_map_snapshots_current_area",
        "map_snapshots",
        ["operational_area_id"],
        unique=True,
        postgresql_where=sa.text("status = 'current'"),
        sqlite_where=sa.text("status = 'current'"),
    )

    op.create_table(
        "map_snapshot_features",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("asset_version_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("asset_type", sa.String(length=50), nullable=False),
        sa.Column("geometry_type", sa.String(length=50), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("geometry", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("verification_state", sa.String(length=30), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("frozen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["operational_area_id"], ["operational_areas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["map_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "asset_id", name="uq_map_snapshot_asset"),
    )
    op.create_index("ix_map_snapshot_features_area", "map_snapshot_features", ["operational_area_id", "snapshot_id"], unique=False)
    op.create_index("ix_map_snapshot_features_type", "map_snapshot_features", ["snapshot_id", "asset_type"], unique=False)
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_map_snapshot_features_postgis_point ON map_snapshot_features USING GIST "
            "((ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography)) "
            "WHERE longitude BETWEEN -180 AND 180 AND latitude BETWEEN -90 AND 90"
        )

    op.create_table(
        "map_package_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_bundle_id", sa.Integer(), nullable=True),
        sa.Column("snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("artifact_kind", sa.String(length=30), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["public_bundle_id"], ["public_map_bundles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["map_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_map_artifacts_snapshot_kind", "map_package_artifacts", ["snapshot_id", "artifact_kind"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_map_artifacts_snapshot_kind", table_name="map_package_artifacts")
    op.drop_table("map_package_artifacts")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_map_snapshot_features_postgis_point")
    op.drop_index("ix_map_snapshot_features_type", table_name="map_snapshot_features")
    op.drop_index("ix_map_snapshot_features_area", table_name="map_snapshot_features")
    op.drop_table("map_snapshot_features")
    op.drop_index("uq_map_snapshots_current_area", table_name="map_snapshots")
    op.drop_index("ix_map_snapshots_version", table_name="map_snapshots")
    op.drop_index("ix_map_snapshots_area_status", table_name="map_snapshots")
    op.drop_table("map_snapshots")
    op.drop_index("ix_public_map_bundles_status", table_name="public_map_bundles")
    op.drop_index("ix_public_map_bundles_id", table_name="public_map_bundles")
    op.drop_index("ix_public_map_bundles_bundle_id", table_name="public_map_bundles")
    op.drop_table("public_map_bundles")
