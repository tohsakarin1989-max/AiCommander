"""Human-recorded facility relationships, separate from proximity/candidates."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class CaseFacilityAssociation(Base):
    __tablename__ = "case_facility_associations"
    __table_args__ = (UniqueConstraint("case_id", "request_key", name="uq_case_facility_request"),)
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("jurisdiction_assets.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_reference_id = Column(Integer, ForeignKey("source_references.id", ondelete="CASCADE"), nullable=False)
    source_revision_id = Column(Integer, ForeignKey("case_revisions.id", ondelete="CASCADE"), nullable=False)
    relation_type = Column(String(30), nullable=False)
    note = Column(Text, nullable=False)
    request_key = Column(String(80), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"))
    revoked_at = Column(DateTime(timezone=True))
    revoke_note = Column(Text)
