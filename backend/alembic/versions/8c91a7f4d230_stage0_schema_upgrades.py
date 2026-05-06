"""stage0 schema upgrades

Revision ID: 8c91a7f4d230
Revises: 4b0f2d2a4e5a
Create Date: 2026-04-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "8c91a7f4d230"
down_revision = "4b0f2d2a4e5a"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(name: str) -> bool:
    return name in _inspector().get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(col["name"] == column_name for col in _inspector().get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(idx["name"] == index_name for idx in _inspector().get_indexes(table_name))


def _create_index_once(index_name: str, table_name: str, columns: list[str]) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if _table_exists("conclusions") and not _column_exists("conclusions", "meeting_id"):
        op.add_column("conclusions", sa.Column("meeting_id", sa.String(length=50), nullable=True))
        _create_index_once("ix_conclusions_meeting_id", "conclusions", ["meeting_id"])

    if not _table_exists("events"):
        op.create_table(
            "events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_number", sa.String(length=50), nullable=False),
            sa.Column("event_type", sa.String(length=50), nullable=False),
            sa.Column("occurred_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("location", sa.String(length=200)),
            sa.Column("latitude", sa.Float()),
            sa.Column("longitude", sa.Float()),
            sa.Column("village_name", sa.String(length=100)),
            sa.Column("village_distance_km", sa.Float()),
            sa.Column("township", sa.String(length=100)),
            sa.Column("title", sa.String(length=200)),
            sa.Column("description", sa.Text()),
            sa.Column("vehicles", sa.JSON()),
            sa.Column("oil_volume_liters", sa.Float()),
            sa.Column("oil_type", sa.String(length=50)),
            sa.Column("equipment", sa.JSON()),
            sa.Column("suspects_count", sa.Integer()),
            sa.Column("suspects_description", sa.Text()),
            sa.Column("discovery_method", sa.String(length=50)),
            sa.Column("handling_result", sa.String(length=100)),
            sa.Column("related_case_id", sa.Integer(), sa.ForeignKey("cases.id")),
            sa.Column("is_analyzed", sa.Boolean(), server_default=sa.text("0")),
            sa.Column("risk_level", sa.String(length=20)),
            sa.Column("analysis_notes", sa.Text()),
            sa.Column("suggested_actions", sa.JSON()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
            sa.Column("created_by", sa.String(length=50)),
            sa.UniqueConstraint("event_number", name="uq_events_event_number"),
        )
    _create_index_once("ix_events_event_number", "events", ["event_number"])
    _create_index_once("ix_events_event_type", "events", ["event_type"])
    _create_index_once("ix_events_latitude", "events", ["latitude"])
    _create_index_once("ix_events_longitude", "events", ["longitude"])
    _create_index_once("ix_events_village", "events", ["village_name"])
    _create_index_once("ix_events_geo", "events", ["latitude", "longitude"])
    _create_index_once("ix_events_type_time", "events", ["event_type", "occurred_time"])

    if not _table_exists("area_profiles"):
        op.create_table(
            "area_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("area_name", sa.String(length=100), nullable=False),
            sa.Column("area_type", sa.String(length=50), server_default="village"),
            sa.Column("center_latitude", sa.Float()),
            sa.Column("center_longitude", sa.Float()),
            sa.Column("radius_km", sa.Float(), server_default="5.0"),
            sa.Column("boundary", sa.JSON()),
            sa.Column("township", sa.String(length=100)),
            sa.Column("county", sa.String(length=100)),
            sa.Column("total_events", sa.Integer(), server_default="0"),
            sa.Column("events_last_30_days", sa.Integer(), server_default="0"),
            sa.Column("events_last_90_days", sa.Integer(), server_default="0"),
            sa.Column("first_event_time", sa.DateTime(timezone=True)),
            sa.Column("last_event_time", sa.DateTime(timezone=True)),
            sa.Column("event_types_count", sa.JSON()),
            sa.Column("risk_level", sa.String(length=20), server_default="low"),
            sa.Column("risk_score", sa.Float(), server_default="0"),
            sa.Column("risk_factors", sa.JSON()),
            sa.Column("risk_updated_at", sa.DateTime(timezone=True)),
            sa.Column("assessment", sa.Text()),
            sa.Column("suggested_actions", sa.JSON()),
            sa.Column("patrol_suggestions", sa.JSON()),
            sa.Column("watch_targets", sa.JSON()),
            sa.Column("related_areas", sa.JSON()),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("1")),
            sa.Column("last_patrol_time", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("area_name", name="uq_area_profiles_area_name"),
        )
    _create_index_once("ix_area_profiles_area_name", "area_profiles", ["area_name"])
    _create_index_once("ix_area_risk", "area_profiles", ["risk_level"])
    _create_index_once("ix_area_geo", "area_profiles", ["center_latitude", "center_longitude"])

    if not _table_exists("event_relations"):
        op.create_table(
            "event_relations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_a_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
            sa.Column("event_b_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
            sa.Column("relation_type", sa.String(length=50), nullable=False),
            sa.Column("confidence", sa.Float(), server_default="0.5"),
            sa.Column("distance_km", sa.Float()),
            sa.Column("time_gap_days", sa.Integer()),
            sa.Column("evidence", sa.Text()),
            sa.Column("reasoning", sa.Text()),
            sa.Column("is_system_generated", sa.Boolean(), server_default=sa.text("1")),
            sa.Column("is_confirmed", sa.Boolean(), server_default=sa.text("0")),
            sa.Column("confirmed_by", sa.String(length=50)),
            sa.Column("confirmed_at", sa.DateTime(timezone=True)),
            sa.Column("is_rejected", sa.Boolean(), server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
    _create_index_once("ix_relation_events", "event_relations", ["event_a_id", "event_b_id"])
    _create_index_once("ix_relation_type", "event_relations", ["relation_type"])

    if not _table_exists("analysis_sessions"):
        op.create_table(
            "analysis_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_number", sa.String(length=50), nullable=False),
            sa.Column("analysis_type", sa.String(length=50), nullable=False),
            sa.Column("title", sa.String(length=200)),
            sa.Column("target_area_id", sa.Integer(), sa.ForeignKey("area_profiles.id")),
            sa.Column("target_event_ids", sa.JSON()),
            sa.Column("context", sa.JSON()),
            sa.Column("questions", sa.JSON()),
            sa.Column("status", sa.String(length=20), server_default="pending"),
            sa.Column("findings", sa.JSON()),
            sa.Column("conclusions", sa.Text()),
            sa.Column("recommendations", sa.JSON()),
            sa.Column("analyst_responses", sa.JSON()),
            sa.Column("consensus_points", sa.JSON()),
            sa.Column("divergence_points", sa.JSON()),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("created_by", sa.String(length=50)),
            sa.UniqueConstraint("session_number", name="uq_analysis_sessions_session_number"),
        )
    _create_index_once("ix_analysis_sessions_session_number", "analysis_sessions", ["session_number"])

    if not _table_exists("patrol_records"):
        op.create_table(
            "patrol_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("patrol_number", sa.String(length=50)),
            sa.Column("patrol_type", sa.String(length=50)),
            sa.Column("area_name", sa.String(length=200)),
            sa.Column("area_coordinates", sa.JSON()),
            sa.Column("start_time", sa.DateTime()),
            sa.Column("end_time", sa.DateTime()),
            sa.Column("patrol_route", sa.JSON()),
            sa.Column("officer_count", sa.Integer(), server_default="1"),
            sa.Column("officer_names", sa.String(length=500)),
            sa.Column("status", sa.String(length=50), server_default="planned"),
            sa.Column("findings", sa.Text()),
            sa.Column("issues_found", sa.Integer(), server_default="0"),
            sa.Column("actions_taken", sa.Text()),
            sa.Column("evidence_photos", sa.JSON()),
            sa.Column("related_case_ids", sa.JSON()),
            sa.Column("related_deployment_id", sa.Integer()),
            sa.Column("risk_before", sa.Float()),
            sa.Column("risk_after", sa.Float()),
            sa.Column("effectiveness_score", sa.Float()),
            sa.Column("feedback_notes", sa.Text()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("created_by", sa.String(length=100)),
            sa.UniqueConstraint("patrol_number", name="uq_patrol_records_patrol_number"),
        )
    _create_index_once("ix_patrol_records_patrol_number", "patrol_records", ["patrol_number"])

    if not _table_exists("area_risk_assessments"):
        op.create_table(
            "area_risk_assessments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("area_name", sa.String(length=200)),
            sa.Column("area_coordinates", sa.JSON()),
            sa.Column("risk_score", sa.Float(), server_default="0"),
            sa.Column("risk_level", sa.String(length=20)),
            sa.Column("case_count_30d", sa.Integer(), server_default="0"),
            sa.Column("case_count_7d", sa.Integer(), server_default="0"),
            sa.Column("patrol_count_30d", sa.Integer(), server_default="0"),
            sa.Column("last_patrol_date", sa.DateTime()),
            sa.Column("days_since_patrol", sa.Integer()),
            sa.Column("risk_history", sa.JSON()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
    _create_index_once("ix_area_risk_assessments_area_name", "area_risk_assessments", ["area_name"])

    if not _table_exists("meeting_templates"):
        op.create_table(
            "meeting_templates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("moderator_model_id", sa.Integer(), nullable=False),
            sa.Column("analyst_model_ids", sa.JSON()),
            sa.Column("config", sa.JSON()),
            sa.Column("is_system", sa.Boolean(), server_default=sa.text("0")),
            sa.Column("use_count", sa.Integer(), server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("name", name="uq_meeting_templates_name"),
        )
    _create_index_once("ix_meeting_templates_name", "meeting_templates", ["name"])

    if not _table_exists("security_personnel"):
        op.create_table(
            "security_personnel",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("badge_number", sa.String(length=50)),
            sa.Column("department", sa.String(length=100)),
            sa.Column("position", sa.String(length=100)),
            sa.Column("phone", sa.String(length=50)),
            sa.Column("status", sa.String(length=20), server_default="active"),
            sa.Column("notes", sa.String(length=500)),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
    _create_index_once("ix_security_personnel_badge_number", "security_personnel", ["badge_number"])

    if not _table_exists("key_locations"):
        op.create_table(
            "key_locations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("location_type", sa.String(length=50), nullable=False),
            sa.Column("latitude", sa.Float()),
            sa.Column("longitude", sa.Float()),
            sa.Column("address", sa.String(length=500)),
            sa.Column("description", sa.String(length=1000)),
            sa.Column("risk_level", sa.Integer(), server_default="1"),
            sa.Column("status", sa.String(length=20), server_default="active"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )


def downgrade() -> None:
    for table in [
        "key_locations",
        "security_personnel",
        "meeting_templates",
        "area_risk_assessments",
        "patrol_records",
        "analysis_sessions",
        "event_relations",
        "area_profiles",
        "events",
    ]:
        if _table_exists(table):
            op.drop_table(table)

    if _column_exists("conclusions", "meeting_id"):
        with op.batch_alter_table("conclusions") as batch_op:
            batch_op.drop_column("meeting_id")
