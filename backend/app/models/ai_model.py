from sqlalchemy import Column, Integer, String, Boolean, JSON, DateTime, Text
from sqlalchemy.sql import func
from app.database import Base

class AIModel(Base):
    __tablename__ = "ai_models"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    provider = Column(String(50), nullable=False)  # openai, anthropic, custom
    model_name = Column(String(100), nullable=False)  # gpt-4, claude-3-opus等
    api_key = Column(Text, nullable=False)  # 加密存储
    role = Column(String(20), nullable=False)  # moderator, analyst
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    config = Column(JSON, default={})  # 温度、最大token等配置
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

