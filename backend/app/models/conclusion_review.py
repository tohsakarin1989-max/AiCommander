from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from app.database import Base


class ConclusionReview(Base):
    __tablename__ = "conclusion_reviews"

    id = Column(Integer, primary_key=True, index=True)
    conclusion_id = Column(Integer, nullable=False, index=True)
    action = Column(String(20), nullable=False)  # approve/reject/flag
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
