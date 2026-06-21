"""辖区基础环境要素模型。"""
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.sql import func

from app.database import Base


class JurisdictionAsset(Base):
    """公共地图参考、油区业务资产和防控设施等空间研判要素。"""

    __tablename__ = "jurisdiction_assets"
    __table_args__ = (
        Index("ix_jurisdiction_assets_type", "asset_type"),
        Index("ix_jurisdiction_assets_source", "source"),
        Index("ix_jurisdiction_assets_status", "status"),
        Index("ix_jurisdiction_assets_geo", "latitude", "longitude"),
    )

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(200), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    asset_type = Column(String(50), nullable=False)
    geometry_type = Column(String(20), default="point")
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    geometry = Column(JSON, nullable=True)
    address = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    source = Column(String(50), default="manual")
    status = Column(String(20), default="active")
    risk_level = Column(Integer, default=1)
    confidence_score = Column(Float, default=1.0)
    verified = Column(Boolean, default=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    tags = Column(JSON, nullable=True)
    attributes = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class JurisdictionFeedback(Base):
    """研判、布防、巡逻执行结果反馈，用于阶段 6 效果评估。"""

    __tablename__ = "jurisdiction_feedback"
    __table_args__ = (
        Index("ix_jurisdiction_feedback_case_id", "case_id"),
        Index("ix_jurisdiction_feedback_type", "feedback_type"),
        Index("ix_jurisdiction_feedback_adopted", "adopted"),
    )

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    asset_id = Column(Integer, ForeignKey("jurisdiction_assets.id"), nullable=True)
    feedback_type = Column(String(50), nullable=False)
    adopted = Column(Boolean, default=False)
    result = Column(Text, nullable=True)
    effectiveness_score = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    extra = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
