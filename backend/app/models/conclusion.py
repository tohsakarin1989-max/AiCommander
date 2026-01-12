from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, Text
from sqlalchemy.sql import func
from app.database import Base


class Conclusion(Base):
    __tablename__ = "conclusions"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, nullable=False, index=True)
    status = Column(String(20), default="draft")  # draft/published/needs_review/rejected/flagged
    confidence = Column(Float, default=0.0)
    risk_level = Column(String(20), default="unknown")  # low/medium/high/unknown
    summary = Column(Text, nullable=True)
    evidence = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
