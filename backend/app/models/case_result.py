"""页面与导出共用的不可变案件成果快照。"""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class CaseResultSnapshot(Base):
    __tablename__ = "case_result_snapshots"
    __table_args__ = (
        UniqueConstraint("case_id", "content_sha256", name="uq_case_result_content"),
        Index("ix_case_results_history", "case_id", "created_at", "id"),
    )

    id = Column(String(36), primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    case_profile_id = Column(String(36), ForeignKey("case_analysis_profiles.id", ondelete="RESTRICT"), nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    content = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
