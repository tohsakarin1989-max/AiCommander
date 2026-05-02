"""数智自动化告警模型。"""
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class AutomationAlert(Base):
    """外部 A2/雷达/云台/AI 视觉链路进入系统后的告警记录。"""

    __tablename__ = "automation_alerts"

    __table_args__ = (
        Index("ix_automation_alerts_number", "alert_number"),
        Index("ix_automation_alerts_status", "status"),
        Index("ix_automation_alerts_type_time", "alert_type", "occurred_time"),
        Index("ix_automation_alerts_geo", "latitude", "longitude"),
    )

    id = Column(Integer, primary_key=True, index=True)
    alert_number = Column(String(50), unique=True, nullable=False)
    source_system = Column(String(100), nullable=False, default="simulated")
    alert_type = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    level = Column(String(20), nullable=False, default="medium")
    risk_level = Column(String(20), nullable=False, default="high")

    occurred_time = Column(DateTime(timezone=True), nullable=False)
    location = Column(String(200))
    latitude = Column(Float)
    longitude = Column(Float)
    facility_id = Column(String(100))
    facility_name = Column(String(200))

    parameter_snapshot = Column(JSON)
    sensing_summary = Column(JSON)
    ai_assessment = Column(JSON)
    suggested_actions = Column(JSON)

    status = Column(String(30), nullable=False, default="pending_review")
    handling_result = Column(String(100))
    review_notes = Column(Text)
    is_simulated = Column(Boolean, default=False)

    related_event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    related_case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    related_event = relationship("Event", foreign_keys=[related_event_id])
    related_case = relationship("Case", foreign_keys=[related_case_id])

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
