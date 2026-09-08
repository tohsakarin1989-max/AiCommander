"""v2.8 今日研判工作台的非敏感效率会话。"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class WorkbenchTaskSession(Base):
    __tablename__ = "workbench_task_sessions"
    __table_args__ = (
        Index("ix_workbench_sessions_user_status", "user_id", "status"),
        Index("ix_workbench_sessions_started", "started_at"),
        Index("ix_workbench_sessions_task_status", "task_type", "status"),
        UniqueConstraint("user_id", "active_slot", name="uq_workbench_user_active_slot"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_type = Column(String(50), nullable=False)
    source_type = Column(String(30), nullable=False)
    source_id = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="active")
    active_slot = Column(Integer, nullable=True)
    entry_path = Column(String(300), nullable=False)
    last_path = Column(String(300), nullable=False)
    page_transitions = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime(timezone=False), nullable=False, default=func.now())
    last_activity_at = Column(DateTime(timezone=False), nullable=False, default=func.now())
    completed_at = Column(DateTime(timezone=False), nullable=True)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=func.now())
