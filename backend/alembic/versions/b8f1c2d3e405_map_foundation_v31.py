"""map foundation v3.1

Revision ID: b8f1c2d3e405
Revises: a7d9e1f2b304
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8f1c2d3e405"
down_revision: Union[str, None] = "a7d9e1f2b304"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        available = op.get_bind().execute(
            sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'postgis'")
        ).scalar()
        if not available:
            raise RuntimeError("v3.1 及以上生产环境必须使用包含 PostGIS 的 PostgreSQL 镜像")
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "operational_areas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("boundary", sa.JSON(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_operational_areas_code", "operational_areas", ["code"], unique=True)
    op.create_index("ix_operational_areas_id", "operational_areas", ["id"], unique=False)
    op.create_index("ix_operational_areas_status", "operational_areas", ["status"], unique=False)

    op.create_table(
        "user_area_scopes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), nullable=False),
        sa.Column("access_level", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["operational_area_id"], ["operational_areas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "operational_area_id", name="uq_user_area_scope"),
    )
    op.create_index(
        "ix_user_area_scope_area_access",
        "user_area_scopes",
        ["operational_area_id", "access_level"],
        unique=False,
    )

    op.create_table(
        "map_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("trust_rank", sa.Integer(), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("configuration", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["operational_area_id"], ["operational_areas.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key"),
    )
    op.create_index("ix_map_sources_area_status", "map_sources", ["operational_area_id", "status"], unique=False)
    op.create_index("ix_map_sources_id", "map_sources", ["id"], unique=False)
    op.create_index("ix_map_sources_source_key", "map_sources", ["source_key"], unique=True)

    op.create_table(
        "map_import_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("sheet_name", sa.String(length=200), nullable=True),
        sa.Column("header_row", sa.Integer(), nullable=False),
        sa.Column("field_mapping", sa.JSON(), nullable=False),
        sa.Column("coordinate_system", sa.String(length=50), nullable=False),
        sa.Column("axis_order", sa.String(length=20), nullable=False),
        sa.Column("coordinate_unit", sa.String(length=20), nullable=False),
        sa.Column("transformation", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["map_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "name", "version", name="uq_map_template_version"),
    )
    op.create_index("ix_map_import_templates_id", "map_import_templates", ["id"], unique=False)
    op.create_index("ix_map_templates_source_active", "map_import_templates", ["source_id", "is_active"], unique=False)

    op.create_table(
        "map_ingest_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("source_revision", sa.String(length=200), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("valid_rows", sa.Integer(), nullable=False),
        sa.Column("quarantined_rows", sa.Integer(), nullable=False),
        sa.Column("created_assets", sa.Integer(), nullable=False),
        sa.Column("updated_assets", sa.Integer(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["map_sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["template_id"], ["map_import_templates.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_map_ingest_idempotency"),
    )
    op.create_index("ix_map_ingest_source_status", "map_ingest_runs", ["source_id", "status"], unique=False)

    with op.batch_alter_table("jurisdiction_assets") as batch_op:
        batch_op.add_column(sa.Column("operational_area_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("canonical_key", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("verification_state", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("coordinate_system", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("accuracy_m", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("source_claim_refs", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_jurisdiction_assets_operational_area",
            "operational_areas",
            ["operational_area_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_jurisdiction_assets_area_type", ["operational_area_id", "asset_type"], unique=False)
        batch_op.create_index("ix_jurisdiction_assets_canonical_key", ["canonical_key"], unique=True)

    with op.batch_alter_table("cases") as batch_op:
        batch_op.add_column(sa.Column("operational_area_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_cases_operational_area",
            "operational_areas",
            ["operational_area_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_cases_operational_area", ["operational_area_id"], unique=False)

    with op.batch_alter_table("jurisdiction_feedback") as batch_op:
        batch_op.add_column(sa.Column("operational_area_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_jurisdiction_feedback_operational_area",
            "operational_areas",
            ["operational_area_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_jurisdiction_feedback_operational_area",
            ["operational_area_id"],
            unique=False,
        )

    with op.batch_alter_table("meetings") as batch_op:
        batch_op.add_column(sa.Column("operational_area_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_meetings_operational_area",
            "operational_areas",
            ["operational_area_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_meetings_operational_area_id",
            ["operational_area_id"],
            unique=False,
        )

    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("operational_area_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_events_operational_area",
            "operational_areas",
            ["operational_area_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_events_operational_area",
            ["operational_area_id"],
            unique=False,
        )

    with op.batch_alter_table("area_profiles") as batch_op:
        batch_op.add_column(sa.Column("operational_area_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_area_profiles_operational_area",
            "operational_areas",
            ["operational_area_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_area_profiles_operational_area",
            ["operational_area_id"],
            unique=False,
        )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_cases_postgis_point ON cases USING GIST "
            "((ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography)) "
            "WHERE longitude BETWEEN -180 AND 180 AND latitude BETWEEN -90 AND 90"
        )
        op.execute(
            "CREATE INDEX ix_assets_postgis_point ON jurisdiction_assets USING GIST "
            "((ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography)) "
            "WHERE longitude BETWEEN -180 AND 180 AND latitude BETWEEN -90 AND 90"
        )

    op.execute(
        sa.text(
            "INSERT INTO operational_areas (code, name, is_default, status) "
            "SELECT 'default-factory', '默认厂区', :is_default, 'active' "
            "WHERE NOT EXISTS (SELECT 1 FROM operational_areas WHERE code = 'default-factory')"
        ).bindparams(is_default=True)
    )
    op.execute(
        sa.text(
            "UPDATE jurisdiction_assets SET operational_area_id = "
            "(SELECT id FROM operational_areas WHERE code = 'default-factory') "
            "WHERE operational_area_id IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE cases SET operational_area_id = "
            "(SELECT id FROM operational_areas WHERE code = 'default-factory') "
            "WHERE operational_area_id IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE events SET operational_area_id = "
            "(SELECT id FROM operational_areas WHERE code = 'default-factory') "
            "WHERE operational_area_id IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE area_profiles SET operational_area_id = "
            "(SELECT id FROM operational_areas WHERE code = 'default-factory') "
            "WHERE operational_area_id IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE jurisdiction_feedback SET operational_area_id = COALESCE("
            "(SELECT cases.operational_area_id FROM cases WHERE cases.id = jurisdiction_feedback.case_id), "
            "(SELECT jurisdiction_assets.operational_area_id FROM jurisdiction_assets "
            " WHERE jurisdiction_assets.id = jurisdiction_feedback.asset_id), "
            "(SELECT id FROM operational_areas WHERE code = 'default-factory')"
            ") WHERE operational_area_id IS NULL"
        )
    )
    if op.get_bind().dialect.name == "postgresql":
        first_case_id = "NULLIF(meetings.case_ids ->> 0, '')::integer"
    else:
        first_case_id = "CAST(json_extract(meetings.case_ids, '$[0]') AS INTEGER)"
    op.execute(
        sa.text(
            "UPDATE meetings SET operational_area_id = COALESCE("
            f"(SELECT cases.operational_area_id FROM cases WHERE cases.id = {first_case_id}), "
            "(SELECT id FROM operational_areas WHERE code = 'default-factory')"
            ") WHERE operational_area_id IS NULL"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO user_area_scopes (user_id, operational_area_id, access_level) "
            "SELECT users.id, operational_areas.id, "
            "CASE WHEN users.role = 'admin' THEN 'manage' "
            "WHEN users.role = 'analyst' THEN 'write' ELSE 'read' END "
            "FROM users JOIN operational_areas ON operational_areas.code = 'default-factory' "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM user_area_scopes "
            "WHERE user_area_scopes.user_id = users.id "
            "AND user_area_scopes.operational_area_id = operational_areas.id"
            ")"
        )
    )

    op.create_table(
        "map_feature_claims",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.String(length=200), nullable=True),
        sa.Column("source_revision", sa.String(length=200), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("normalized_payload", sa.JSON(), nullable=True),
        sa.Column("raw_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["jurisdiction_assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["map_ingest_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["map_sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "row_number", name="uq_map_claim_run_row"),
    )
    op.create_index("ix_map_claims_asset", "map_feature_claims", ["asset_id"], unique=False)
    op.create_index("ix_map_claims_source_status", "map_feature_claims", ["source_id", "status"], unique=False)

    op.create_table(
        "jurisdiction_asset_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_claim_id", sa.Integer(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("change_type", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["jurisdiction_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_claim_id"], ["map_feature_claims.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "version", name="uq_jurisdiction_asset_version"),
    )
    op.create_index("ix_asset_versions_claim", "jurisdiction_asset_versions", ["source_claim_id"], unique=False)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_assets_postgis_point")
        op.execute("DROP INDEX IF EXISTS ix_cases_postgis_point")
    op.drop_index("ix_asset_versions_claim", table_name="jurisdiction_asset_versions")
    op.drop_table("jurisdiction_asset_versions")
    op.drop_index("ix_map_claims_source_status", table_name="map_feature_claims")
    op.drop_index("ix_map_claims_asset", table_name="map_feature_claims")
    op.drop_table("map_feature_claims")

    with op.batch_alter_table("area_profiles") as batch_op:
        batch_op.drop_index("ix_area_profiles_operational_area")
        batch_op.drop_constraint("fk_area_profiles_operational_area", type_="foreignkey")
        batch_op.drop_column("operational_area_id")

    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_index("ix_events_operational_area")
        batch_op.drop_constraint("fk_events_operational_area", type_="foreignkey")
        batch_op.drop_column("operational_area_id")

    with op.batch_alter_table("jurisdiction_feedback") as batch_op:
        batch_op.drop_index("ix_jurisdiction_feedback_operational_area")
        batch_op.drop_constraint("fk_jurisdiction_feedback_operational_area", type_="foreignkey")
        batch_op.drop_column("operational_area_id")

    with op.batch_alter_table("meetings") as batch_op:
        batch_op.drop_index("ix_meetings_operational_area_id")
        batch_op.drop_constraint("fk_meetings_operational_area", type_="foreignkey")
        batch_op.drop_column("operational_area_id")

    with op.batch_alter_table("cases") as batch_op:
        batch_op.drop_index("ix_cases_operational_area")
        batch_op.drop_constraint("fk_cases_operational_area", type_="foreignkey")
        batch_op.drop_column("operational_area_id")

    with op.batch_alter_table("jurisdiction_assets") as batch_op:
        batch_op.drop_index("ix_jurisdiction_assets_canonical_key")
        batch_op.drop_index("ix_jurisdiction_assets_area_type")
        batch_op.drop_constraint("fk_jurisdiction_assets_operational_area", type_="foreignkey")
        batch_op.drop_column("valid_to")
        batch_op.drop_column("valid_from")
        batch_op.drop_column("source_claim_refs")
        batch_op.drop_column("accuracy_m")
        batch_op.drop_column("coordinate_system")
        batch_op.drop_column("verification_state")
        batch_op.drop_column("canonical_key")
        batch_op.drop_column("operational_area_id")

    op.drop_index("ix_map_ingest_source_status", table_name="map_ingest_runs")
    op.drop_table("map_ingest_runs")
    op.drop_index("ix_map_templates_source_active", table_name="map_import_templates")
    op.drop_index("ix_map_import_templates_id", table_name="map_import_templates")
    op.drop_table("map_import_templates")
    op.drop_index("ix_map_sources_source_key", table_name="map_sources")
    op.drop_index("ix_map_sources_id", table_name="map_sources")
    op.drop_index("ix_map_sources_area_status", table_name="map_sources")
    op.drop_table("map_sources")
    op.drop_index("ix_user_area_scope_area_access", table_name="user_area_scopes")
    op.drop_table("user_area_scopes")
    op.drop_index("ix_operational_areas_status", table_name="operational_areas")
    op.drop_index("ix_operational_areas_id", table_name="operational_areas")
    op.drop_index("ix_operational_areas_code", table_name="operational_areas")
    op.drop_table("operational_areas")
