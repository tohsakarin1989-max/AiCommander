from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from app.database import Base

class Report(Base):
    __tablename__ = "reports"
    
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(String(64), ForeignKey("meetings.meeting_id"), index=True)
    report_type = Column(String(20))  # comprehensive, summary
    content = Column(JSON, nullable=False)
    consensus_points = Column(JSON)
    disagreement_points = Column(JSON)
    model_contributions = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

