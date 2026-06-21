"""case management requirements upgrade

Revision ID: b7a94f31c2d6
Revises: 8c91a7f4d230
Create Date: 2026-04-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "b7a94f31c2d6"
down_revision = "8c91a7f4d230"
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


def _add_column_once(table_name: str, column: sa.Column) -> None:
    if _table_exists(table_name) and not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def _create_index_once(index_name: str, table_name: str, columns: list[str]) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    case_columns = [
        sa.Column("report_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_unit", sa.String(length=100), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=True),
        sa.Column("source_detail", sa.Text(), nullable=True),
        sa.Column("police_reported", sa.Boolean(), nullable=True),
        sa.Column("case_filed", sa.Boolean(), nullable=True),
        sa.Column("police_officer", sa.String(length=100), nullable=True),
        sa.Column("police_phone", sa.String(length=50), nullable=True),
        sa.Column("security_officers", sa.JSON(), nullable=True),
        sa.Column("oil_nature", sa.String(length=50), nullable=True),
        sa.Column("water_cut", sa.Float(), nullable=True),
        sa.Column("vehicle_handling", sa.String(length=100), nullable=True),
        sa.Column("person_handling", sa.String(length=100), nullable=True),
        sa.Column("oil_handling", sa.String(length=100), nullable=True),
        sa.Column("operation_role", sa.String(length=50), nullable=True),
        sa.Column("current_stage", sa.String(length=50), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("quality_level", sa.String(length=20), nullable=True),
        sa.Column("quality_issues", sa.JSON(), nullable=True),
        sa.Column("quality_updated_at", sa.DateTime(timezone=True), nullable=True),
    ]
    for column in case_columns:
        _add_column_once("cases", column)

    _create_index_once("ix_cases_report_time", "cases", ["report_time"])
    _create_index_once("ix_cases_source_type", "cases", ["source_type"])
    _create_index_once("ix_cases_report_unit", "cases", ["report_unit"])
    _create_index_once("ix_cases_current_stage", "cases", ["current_stage"])
    _create_index_once("ix_cases_quality_level", "cases", ["quality_level"])

    if not _table_exists("case_vehicles"):
        op.create_table(
            "case_vehicles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id"), nullable=False),
            sa.Column("vehicle_type", sa.String(length=50), nullable=True),
            sa.Column("color", sa.String(length=50), nullable=True),
            sa.Column("brand", sa.String(length=100), nullable=True),
            sa.Column("model", sa.String(length=100), nullable=True),
            sa.Column("plate_number", sa.String(length=50), nullable=True),
            sa.Column("oil_volume", sa.Float(), nullable=True),
            sa.Column("water_cut", sa.Float(), nullable=True),
            sa.Column("custody_location", sa.String(length=200), nullable=True),
            sa.Column("current_location", sa.String(length=200), nullable=True),
            sa.Column("handling_status", sa.String(length=100), nullable=True),
            sa.Column("transferred_to_police", sa.Boolean(), nullable=True),
            sa.Column("transfer_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("transfer_document_no", sa.String(length=100), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    _create_index_once("ix_case_vehicles_case_id", "case_vehicles", ["case_id"])
    _create_index_once("ix_case_vehicles_plate_number", "case_vehicles", ["plate_number"])
    _create_index_once("ix_case_vehicles_handling_status", "case_vehicles", ["handling_status"])

    if not _table_exists("case_persons"):
        op.create_table(
            "case_persons",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id"), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=True),
            sa.Column("gender", sa.String(length=20), nullable=True),
            sa.Column("id_number", sa.String(length=50), nullable=True),
            sa.Column("home_address", sa.String(length=300), nullable=True),
            sa.Column("phone", sa.String(length=50), nullable=True),
            sa.Column("role", sa.String(length=50), nullable=True),
            sa.Column("handling_status", sa.String(length=100), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    _create_index_once("ix_case_persons_case_id", "case_persons", ["case_id"])
    _create_index_once("ix_case_persons_name", "case_persons", ["name"])
    _create_index_once("ix_case_persons_id_number", "case_persons", ["id_number"])

    if not _table_exists("case_evidence"):
        op.create_table(
            "case_evidence",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id"), nullable=False),
            sa.Column("evidence_type", sa.String(length=50), nullable=True),
            sa.Column("title", sa.String(length=200), nullable=True),
            sa.Column("file_path", sa.String(length=500), nullable=True),
            sa.Column("requirement_key", sa.String(length=100), nullable=True),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("is_sensitive", sa.Boolean(), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    _create_index_once("ix_case_evidence_case_id", "case_evidence", ["case_id"])
    _create_index_once("ix_case_evidence_type", "case_evidence", ["evidence_type"])
    _create_index_once("ix_case_evidence_requirement", "case_evidence", ["requirement_key"])

    if not _table_exists("oil_recovery_records"):
        op.create_table(
            "oil_recovery_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id"), nullable=False),
            sa.Column("oil_nature", sa.String(length=50), nullable=True),
            sa.Column("volume_tons", sa.Float(), nullable=True),
            sa.Column("water_cut", sa.Float(), nullable=True),
            sa.Column("source", sa.String(length=200), nullable=True),
            sa.Column("receiver", sa.String(length=200), nullable=True),
            sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("handling_method", sa.String(length=100), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    _create_index_once("ix_oil_recovery_case_id", "oil_recovery_records", ["case_id"])
    _create_index_once("ix_oil_recovery_oil_nature", "oil_recovery_records", ["oil_nature"])

    if not _table_exists("case_tips"):
        op.create_table(
            "case_tips",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id"), nullable=True),
            sa.Column("reporter_name", sa.String(length=100), nullable=True),
            sa.Column("reporter_contact", sa.String(length=100), nullable=True),
            sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("location", sa.String(length=200), nullable=True),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("source_type", sa.String(length=50), nullable=True),
            sa.Column("verification_status", sa.String(length=50), nullable=True),
            sa.Column("resolution", sa.Text(), nullable=True),
            sa.Column("prevention_actions", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    _create_index_once("ix_case_tips_case_id", "case_tips", ["case_id"])
    _create_index_once("ix_case_tips_reported_at", "case_tips", ["reported_at"])
    _create_index_once("ix_case_tips_verification_status", "case_tips", ["verification_status"])


def downgrade() -> None:
    for table in ("case_tips", "oil_recovery_records", "case_evidence", "case_persons", "case_vehicles"):
        if _table_exists(table):
            op.drop_table(table)

    for column_name in (
        "quality_updated_at",
        "quality_issues",
        "quality_level",
        "quality_score",
        "current_stage",
        "operation_role",
        "oil_handling",
        "person_handling",
        "vehicle_handling",
        "water_cut",
        "oil_nature",
        "security_officers",
        "police_phone",
        "police_officer",
        "case_filed",
        "police_reported",
        "source_detail",
        "source_type",
        "report_unit",
        "report_time",
    ):
        if _column_exists("cases", column_name):
            op.drop_column("cases", column_name)
