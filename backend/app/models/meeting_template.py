"""
会议模板模型
预定义分析员组合+专家角色模板
"""
from sqlalchemy import Column, Integer, String, DateTime, JSON, Text, Boolean
from sqlalchemy.sql import func
from app.database import Base


class MeetingTemplate(Base):
    __tablename__ = "meeting_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    moderator_model_id = Column(Integer, nullable=False)  # 主持人模型ID
    analyst_model_ids = Column(JSON, default=[])  # 分析员模型ID列表
    # 模板配置：可以包含专家角色描述、分析重点等
    config = Column(JSON, default={})
    # 是否为系统预置模板
    is_system = Column(Boolean, default=False)
    # 使用次数统计
    use_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
