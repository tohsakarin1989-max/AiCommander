"""Source identities and declared/received facility history; no guessed backfill."""
from alembic import op
import sqlalchemy as sa

revision = "v62i01"
down_revision = "v61s01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("facility_source_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("map_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), sa.ForeignKey("operational_areas.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("native_asset_id", sa.Integer(), sa.ForeignKey("jurisdiction_assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("identity_key", sa.String(280), nullable=False),
        sa.Column("source_record_id", sa.String(200)), sa.Column("asset_type", sa.String(50), nullable=False),
        sa.Column("identity_kind", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", "identity_key", name="uq_facility_source_identity"))
    op.create_index("ix_facility_identity_area_asset", "facility_source_identities", ["operational_area_id", "native_asset_id"])
    op.create_table("facility_identity_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("facility_source_identities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operational_area_id", sa.Integer(), sa.ForeignKey("operational_areas.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_asset_id", sa.Integer(), sa.ForeignKey("jurisdiction_assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("action", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("note", sa.Text(), nullable=False), sa.Column("request_key", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("identity_id", "sequence", name="uq_facility_identity_decision_seq"),
        sa.UniqueConstraint("identity_id", "request_key", name="uq_facility_identity_decision_request"),
        sa.CheckConstraint("action IN ('bind','revoke')", name="ck_facility_identity_decision_action"))
    op.create_index("ix_facility_identity_decisions_identity_id", "facility_identity_decisions", ["identity_id"])
    for table in ("map_feature_claims", "jurisdiction_asset_versions"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("source_identity_id", sa.Integer()))
            batch.add_column(sa.Column("identity_decision_id", sa.Integer()))
            batch.create_foreign_key(f"fk_{table}_identity", "facility_source_identities", ["source_identity_id"], ["id"], ondelete="RESTRICT")
            batch.create_foreign_key(f"fk_{table}_decision", "facility_identity_decisions", ["identity_decision_id"], ["id"], ondelete="RESTRICT")
    with op.batch_alter_table("jurisdiction_asset_versions") as batch:
        batch.add_column(sa.Column("valid_from", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("valid_to", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("known_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("temporal_status", sa.String(20), nullable=False, server_default="observed_only"))
        batch.create_check_constraint("ck_asset_version_interval", "valid_to IS NULL OR (valid_from IS NOT NULL AND valid_to > valid_from)")
        batch.create_check_constraint("ck_asset_version_temporal_status", "temporal_status IN ('declared','observed_only')")
        batch.create_index("ix_asset_versions_temporal", ["asset_id", "known_at", "valid_from"])


def downgrade():
    raise RuntimeError("restore_compatible_backup_required_for_facility_identity_downgrade")
