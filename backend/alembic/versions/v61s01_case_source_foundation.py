"""Typed intake and immutable source versions, without converting existing facts."""
from alembic import op
import sqlalchemy as sa

revision = "v61s01"
down_revision = "v60c01"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", sa.Integer(), primary_key=True)


def _case():
    return sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)


def _actor():
    return sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"))


def _created():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade():
    with op.batch_alter_table("cases") as batch:
        batch.alter_column("occurred_time", existing_type=sa.DateTime(timezone=True), nullable=True)
        for name in ("occurred_from", "occurred_to", "discovered_at"):
            batch.add_column(sa.Column(name, sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("time_precision", sa.String(20), nullable=True))
        batch.add_column(sa.Column("time_expression", sa.Text()))
        batch.add_column(sa.Column("time_timezone", sa.String(80), nullable=False, server_default="Asia/Shanghai"))
        batch.add_column(sa.Column("oil_volume_unit", sa.String(20), nullable=False, server_default="unknown"))
    op.add_column("case_vehicles", sa.Column("oil_volume_unit", sa.String(20), nullable=False, server_default="unknown"))
    with op.batch_alter_table("case_tips") as batch:
        batch.add_column(sa.Column("operational_area_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_case_tip_area", "operational_areas", ["operational_area_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_case_tips_operational_area_id", ["operational_area_id"])
    op.create_table("case_locations", _id(), _case(),
        sa.Column("role", sa.String(30), nullable=False), sa.Column("description", sa.Text()),
        sa.Column("geometry", sa.JSON()), sa.Column("precision", sa.String(20), nullable=False),
        sa.Column("source_note", sa.Text()),
        sa.CheckConstraint("role IN ('incident','discovery','mentioned','source_candidate','custody')", name="ck_case_location_role"),
        sa.CheckConstraint("precision IN ('exact','area','unknown')", name="ck_case_location_precision"))
    op.create_table("oil_measurements", _id(), _case(),
        sa.Column("value", sa.Float(), nullable=False), sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False), sa.Column("method", sa.Text()),
        sa.Column("measured_at", sa.DateTime(timezone=True)), sa.Column("water_cut", sa.Float()),
        sa.Column("water_cut_basis", sa.String(100)), sa.Column("source_note", sa.Text()),
        sa.CheckConstraint("value >= 0", name="ck_oil_measurement_value"),
        sa.CheckConstraint("unit IN ('tonne','liter','kg','m3','unknown')", name="ck_oil_measurement_unit"),
        sa.CheckConstraint("stage IN ('involved','seized','transferred','recovered','unknown')", name="ck_oil_measurement_stage"))
    op.create_table("case_revisions", _id(), _case(),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False), _actor(), _created(),
        sa.UniqueConstraint("case_id", "revision", name="uq_case_revision_sequence"))
    op.create_table("domain_changes", _id(),
        sa.Column("subject_type", sa.String(40), nullable=False), sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("source_revision_id", sa.Integer(), sa.ForeignKey("case_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("change_type", sa.String(40), nullable=False), _actor(), _created(),
        sa.UniqueConstraint("subject_type", "subject_id", "source_revision_id", name="uq_domain_change_revision"))
    op.create_table("change_deliveries", _id(),
        sa.Column("change_id", sa.Integer(), sa.ForeignKey("domain_changes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("consumer", sa.String(80), nullable=False), sa.Column("state", sa.String(30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("error", sa.Text()),
        sa.UniqueConstraint("change_id", "consumer", name="uq_change_delivery_consumer"))
    op.create_table("evidence_objects", _id(),
        sa.Column("storage_key", sa.String(200), nullable=False, unique=True), sa.Column("sha256", sa.String(64)),
        sa.Column("media_type", sa.String(100)), sa.Column("sensitivity", sa.String(30), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True)), sa.Column("availability", sa.String(30), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.CheckConstraint("availability IN ('metadata_only','available','revoked')", name="ck_evidence_availability"))
    op.create_table("source_references", _id(), _case(),
        sa.Column("source_revision_id", sa.Integer(), sa.ForeignKey("case_revisions.id", ondelete="CASCADE")),
        sa.Column("evidence_object_id", sa.Integer(), sa.ForeignKey("evidence_objects.id", ondelete="RESTRICT")),
        sa.Column("kind", sa.String(40), nullable=False), sa.Column("locator", sa.JSON(), nullable=False))
    op.create_table("case_source_links", _id(), _case(),
        sa.Column("source_type", sa.String(20), nullable=False), sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False), _created(),
        sa.UniqueConstraint("source_type", "source_id", "case_id", name="uq_case_source_link"),
        sa.CheckConstraint("source_type IN ('event','tip')", name="ck_case_source_link_type"))
    for table in ("case_locations", "oil_measurements", "case_revisions", "source_references", "case_source_links"):
        op.create_index(f"ix_{table}_case_id", table, ["case_id"])
    op.create_index("ix_domain_changes_subject_id", "domain_changes", ["subject_id"])
    with op.batch_alter_table("case_evidence") as batch:
        batch.add_column(sa.Column("evidence_object_id", sa.Integer()))
        batch.add_column(sa.Column("source_reference_id", sa.Integer()))
        batch.create_foreign_key("fk_case_evidence_object", "evidence_objects", ["evidence_object_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_case_evidence_reference", "source_references", ["source_reference_id"], ["id"], ondelete="RESTRICT")
    with op.batch_alter_table("outbox_events") as batch:
        batch.add_column(sa.Column("domain_change_id", sa.Integer()))
        batch.create_foreign_key("fk_outbox_domain_change", "domain_changes", ["domain_change_id"], ["id"], ondelete="SET NULL")
    with op.batch_alter_table("case_analysis_profiles") as batch:
        batch.alter_column("quality_score", existing_type=sa.Float(), nullable=True)
        batch.add_column(sa.Column("source_revision_id", sa.Integer()))
        batch.create_foreign_key("fk_profile_source_revision", "case_revisions", ["source_revision_id"], ["id"], ondelete="CASCADE")
        batch.drop_constraint("uq_case_profile_input_version", type_="unique")
        batch.create_unique_constraint("uq_case_profile_input_version",
            ["case_id", "source_hash", "schema_version", "dictionary_version", "source_revision_id"])


def downgrade():
    raise RuntimeError("restore_compatible_backup_required_for_source_revision_downgrade")
