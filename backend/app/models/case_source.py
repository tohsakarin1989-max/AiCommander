"""Typed source records and immutable revisions; not analysis output."""
from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, JSON, LargeBinary, String, Text, UniqueConstraint, event
from sqlalchemy.orm import deferred
from sqlalchemy.sql import func

from app.database import Base


class CaseLocation(Base):
    __tablename__ = "case_locations"
    __table_args__ = (
        CheckConstraint("role IN ('incident','discovery','mentioned','source_candidate','custody')", name="ck_case_location_role"),
        CheckConstraint("precision IN ('exact','area','unknown')", name="ck_case_location_precision"),
    )
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(30), nullable=False)
    description = Column(Text)
    geometry = Column(JSON)
    precision = Column(String(20), nullable=False, default="unknown")
    source_note = Column(Text)


class OilMeasurement(Base):
    __tablename__ = "oil_measurements"
    __table_args__ = (
        CheckConstraint("value >= 0", name="ck_oil_measurement_value"),
        CheckConstraint("unit IN ('tonne','liter','kg','m3','unknown')", name="ck_oil_measurement_unit"),
        CheckConstraint("stage IN ('involved','seized','transferred','recovered','unknown')", name="ck_oil_measurement_stage"),
    )
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    value = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False, default="unknown")
    stage = Column(String(20), nullable=False, default="unknown")
    method = Column(Text)
    measured_at = Column(DateTime(timezone=True))
    water_cut = Column(Float)
    water_cut_basis = Column(String(100))
    source_note = Column(Text)


class CaseRevision(Base):
    __tablename__ = "case_revisions"
    __table_args__ = (UniqueConstraint("case_id", "revision", name="uq_case_revision_sequence"),)
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    source_hash = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DomainChange(Base):
    __tablename__ = "domain_changes"
    __table_args__ = (UniqueConstraint("subject_type", "subject_id", "source_revision_id", name="uq_domain_change_revision"),)
    id = Column(Integer, primary_key=True)
    subject_type = Column(String(40), nullable=False)
    subject_id = Column(Integer, nullable=False, index=True)
    source_revision_id = Column(Integer, ForeignKey("case_revisions.id", ondelete="CASCADE"), nullable=False)
    change_type = Column(String(40), nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ChangeDelivery(Base):
    __tablename__ = "change_deliveries"
    __table_args__ = (UniqueConstraint("change_id", "consumer", name="uq_change_delivery_consumer"),)
    id = Column(Integer, primary_key=True)
    change_id = Column(Integer, ForeignKey("domain_changes.id", ondelete="CASCADE"), nullable=False)
    consumer = Column(String(80), nullable=False)
    state = Column(String(30), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    error = Column(Text)


class EvidenceObject(Base):
    __tablename__ = "evidence_objects"
    __table_args__ = (CheckConstraint("availability IN ('metadata_only','available','revoked')", name="ck_evidence_availability"),)
    id = Column(Integer, primary_key=True)
    storage_key = Column(String(200), nullable=False, unique=True)
    sha256 = Column(String(64))
    media_type = Column(String(100))
    sensitivity = Column(String(30), nullable=False, default="internal")
    captured_at = Column(DateTime(timezone=True))
    availability = Column(String(30), nullable=False, default="metadata_only")
    content = deferred(Column(LargeBinary, nullable=True))


class SourceReference(Base):
    __tablename__ = "source_references"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    source_revision_id = Column(Integer, ForeignKey("case_revisions.id", ondelete="CASCADE"))
    evidence_object_id = Column(Integer, ForeignKey("evidence_objects.id", ondelete="RESTRICT"))
    kind = Column(String(40), nullable=False)
    locator = Column(JSON, nullable=False, default=dict)


class CaseSourceLink(Base):
    __tablename__ = "case_source_links"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "case_id", name="uq_case_source_link"),
        CheckConstraint("source_type IN ('event','tip')", name="ck_case_source_link_type"),
    )
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(20), nullable=False)
    source_id = Column(Integer, nullable=False)
    source_snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _immutable_source(mapper, connection, target):
    raise ValueError("source_record_is_immutable")


for _model in (CaseRevision, DomainChange, CaseSourceLink):
    event.listen(_model, "before_update", _immutable_source)
