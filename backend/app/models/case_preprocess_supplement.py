"""Optional model wording, separate from immutable profiles and original facts."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class CasePreprocessSupplement(Base):
    __tablename__ = "case_preprocess_supplements"
    __table_args__ = (UniqueConstraint("case_profile_id", "model_fingerprint",
                                     name="uq_case_preprocess_supplement_input"),)

    id = Column(String(36), primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    case_profile_id = Column(String(36), ForeignKey("case_analysis_profiles.id", ondelete="CASCADE"), nullable=False)
    source_revision_id = Column(Integer, ForeignKey("case_revisions.id", ondelete="CASCADE"), nullable=False)
    model_fingerprint = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
