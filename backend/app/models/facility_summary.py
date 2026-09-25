"""Rebuildable catalog projection, not another asset register or case fact."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Index
from sqlalchemy.sql import func

from app.database import Base


class FacilityDerivedSummary(Base):
    __tablename__ = 'facility_derived_summaries'
    __table_args__ = (Index('ix_facility_summary_checked', 'checked_at'),)
    asset_id = Column(Integer, ForeignKey('jurisdiction_assets.id', ondelete='CASCADE'), primary_key=True)
    revision = Column(Integer, nullable=False)
    algorithm_version = Column(String(80), nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    changes = Column(JSON, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    checked_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
