from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from app.database import Base


class PreprocessJob(Base):
  __tablename__ = "preprocess_jobs"

  id = Column(Integer, primary_key=True, index=True)
  case_id = Column(Integer, ForeignKey("cases.id"), index=True, nullable=False)
  status = Column(String(20), nullable=False, index=True)  # queued / processing / success / failed
  created_at = Column(DateTime(timezone=True), server_default=func.now())
  started_at = Column(DateTime(timezone=True), nullable=True)
  finished_at = Column(DateTime(timezone=True), nullable=True)
  error = Column(Text, nullable=True)


