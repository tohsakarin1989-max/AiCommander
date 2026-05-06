"""
保卫人员信息模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from app.database import Base


class SecurityPersonnel(Base):
    __tablename__ = "security_personnel"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    badge_number = Column(String(50), index=True)
    department = Column(String(100))
    position = Column(String(100))
    phone = Column(String(50))
    status = Column(String(20), default="active")  # active, inactive, on_leave
    notes = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
