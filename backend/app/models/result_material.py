"""Typed material storage and optional, append-only human decisions."""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class FacilityMaterial(Base):
    __tablename__ = 'facility_materials'
    __table_args__ = (UniqueConstraint('created_by', 'idempotency_key', name='uq_facility_material_request'),)
    id = Column(String(36), primary_key=True)
    asset_id = Column(Integer, ForeignKey('jurisdiction_assets.id', ondelete='RESTRICT'), nullable=False)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    title = Column(String(240), nullable=False)
    idempotency_key = Column(String(80), nullable=False)
    request_sha256 = Column(String(64), nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    source_manifest = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ResultJudgment(Base):
    __tablename__ = 'result_judgments'
    __table_args__ = (
        UniqueConstraint('created_by', 'idempotency_key', name='uq_result_judgment_request'),
        Index('ix_result_judgment_version', 'result_kind', 'result_id', 'content_sha256'),
    )
    id = Column(String(36), primary_key=True)
    result_kind = Column(String(24), nullable=False)
    result_id = Column(String(80), nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    decision = Column(String(40), nullable=False)
    note = Column(Text, nullable=False)
    additional_sources = Column(JSON, nullable=False)
    idempotency_key = Column(String(80), nullable=False)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MeetingFrozenInput(Base):
    __tablename__ = 'meeting_frozen_inputs'
    meeting_id = Column(String(64), ForeignKey('meetings.meeting_id', ondelete='RESTRICT'), primary_key=True)
    content_sha256 = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
