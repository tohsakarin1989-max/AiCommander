from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.sql import func
from app.database import Base

class SystemConfig(Base):
    """系统配置表 - 存储各种API密钥和系统设置"""
    __tablename__ = "system_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    config_key = Column(String(100), unique=True, nullable=False, index=True)  # 配置键，如 map_api_key, meeting_api_key
    config_value = Column(Text, nullable=True)  # 配置值（API密钥等）
    config_type = Column(String(50), nullable=False)  # 配置类型：api_key, url, json等
    category = Column(String(50), nullable=False)  # 分类：map, meeting, general等
    description = Column(Text)  # 配置说明
    is_encrypted = Column(String(10), default="false")  # 是否加密存储（暂未实现加密，标记用）
    extra_data = Column(JSON)  # 额外配置数据（如API提供商、服务地址等）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

