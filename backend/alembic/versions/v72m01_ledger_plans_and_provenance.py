"""Ledger plans, row corrections and coupled-field provenance.

Revision ID: v72m01
Revises: v71d01
"""
from alembic import op
import sqlalchemy as sa


revision = "v72m01"
down_revision = "v71d01"
branch_labels = None
depends_on = None

DETAIL_TABLES = (
    "case_locations", "oil_measurements", "case_vehicles", "case_persons", "case_evidence",
    "oil_recovery_records", "case_tips", "case_source_links", "evidence_objects", "source_references",
)


def _upgrade_tables():
    if op.get_bind().dialect.name == "sqlite":
        for table in DETAIL_TABLES:
            with op.batch_alter_table(table, recreate="always", table_kwargs={"sqlite_autoincrement": True}):
                pass
    with op.batch_alter_table("map_import_templates") as batch:
        batch.add_column(sa.Column("expected_structure", sa.JSON()))
        batch.add_column(sa.Column("field_units", sa.JSON()))
    with op.batch_alter_table("map_ingest_runs") as batch:
        batch.add_column(sa.Column("request_sha256", sa.String(64)))
        batch.add_column(sa.Column("table_metadata", sa.JSON()))
        batch.add_column(sa.Column("template_snapshot", sa.JSON()))
        batch.add_column(sa.Column("classification_counts", sa.JSON()))
        batch.add_column(sa.Column("parent_run_id", sa.String(36)))
        batch.add_column(sa.Column("original_evidence_object_id", sa.Integer()))
        batch.create_foreign_key("fk_map_ingest_parent", "map_ingest_runs", ["parent_run_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_map_ingest_original", "evidence_objects", ["original_evidence_object_id"], ["id"], ondelete="RESTRICT")
    with op.batch_alter_table("map_feature_claims") as batch:
        batch.add_column(sa.Column("parent_claim_id", sa.Integer()))
        batch.add_column(sa.Column("plan", sa.JSON()))
        batch.add_column(sa.Column("correction_note", sa.Text()))
        batch.create_foreign_key("fk_map_claim_parent", "map_feature_claims", ["parent_claim_id"], ["id"], ondelete="RESTRICT")
    op.create_table("map_field_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("jurisdiction_assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("map_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("claim_id", sa.Integer(), sa.ForeignKey("map_feature_claims.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("group_key", sa.String(40), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("previous_decision_id", sa.Integer(), sa.ForeignKey("map_field_decisions.id", ondelete="RESTRICT")),
        sa.Column("valid_from", sa.DateTime(timezone=True)), sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("claim_id", "group_key", name="uq_map_field_decision_claim_group"))
    op.create_index("ix_map_field_decision_asset_group", "map_field_decisions", ["asset_id", "group_key", "id"])


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "sqlite":
        _upgrade_tables()
        return
    if connection.exec_driver_sql("PRAGMA foreign_key_check").first():
        raise RuntimeError("v72_existing_foreign_key_violation_requires_repair")
    # Only this isolated migration connection changes enforcement, outside a
    # transaction so SQLite actually applies it. All records and dependencies
    # are checked before restoring enforcement; application connections stay on.
    with op.get_context().autocommit_block():
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        _upgrade_tables()
        if connection.exec_driver_sql("PRAGMA foreign_key_check").first():
            raise RuntimeError("v72_rebuild_foreign_key_check_failed_restore_backup")
    finally:
        with op.get_context().autocommit_block():
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def downgrade():
    for statement in ("SELECT 1 FROM map_field_decisions LIMIT 1",
                      "SELECT 1 FROM map_ingest_runs WHERE classification_counts IS NOT NULL LIMIT 1"):
        if op.get_bind().execute(sa.text(statement)).first():
            raise RuntimeError("v72_ledger_provenance_requires_compatible_backup_before_downgrade")
    op.drop_table("map_field_decisions")
    with op.batch_alter_table("map_feature_claims") as batch:
        batch.drop_constraint("fk_map_claim_parent", type_="foreignkey")
        for column in ("parent_claim_id", "plan", "correction_note"):
            batch.drop_column(column)
    with op.batch_alter_table("map_ingest_runs") as batch:
        batch.drop_constraint("fk_map_ingest_parent", type_="foreignkey")
        batch.drop_constraint("fk_map_ingest_original", type_="foreignkey")
        for column in ("table_metadata", "template_snapshot", "classification_counts", "parent_run_id", "original_evidence_object_id", "request_sha256"):
            batch.drop_column(column)
    with op.batch_alter_table("map_import_templates") as batch:
        batch.drop_column("expected_structure")
        batch.drop_column("field_units")
    # Retain SQLite AUTOINCREMENT: reverting it would permit historical IDs to
    # be reused. It is backward-compatible with the preceding application.
