"""Private, expiring form snapshots; never part of the Case source pipeline."""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, JSON, String

from app.database import Base


class CaseDraft(Base):
    __tablename__ = "case_drafts"
    __table_args__ = (
        CheckConstraint("status IN ('active','submitted')", name="ck_case_draft_status"),
        CheckConstraint("mode IN ('create','edit')", name="ck_case_draft_mode"),
        Index("ix_case_drafts_owner_expiry", "owner_id", "expires_at"),
    )
    id = Column(String(36), primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    operational_area_id = Column(Integer, ForeignKey("operational_areas.id", ondelete="CASCADE"), nullable=False)
    mode = Column(String(10), nullable=False)
    target_case_id = Column(Integer, ForeignKey("cases.id", ondelete="SET NULL"))
    base_case_revision = Column(Integer)
    revision = Column(Integer, nullable=False)
    schema_version = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)
    form_snapshot = Column(JSON, nullable=False)
    last_save_sha256 = Column(String(64), nullable=False)
    submission_key = Column(String(128), nullable=False)
    submission_sha256 = Column(String(64))
    submitted_case_id = Column(Integer, ForeignKey("cases.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
