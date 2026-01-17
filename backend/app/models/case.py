from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Float, Index
from sqlalchemy.sql import func
from app.database import Base

class Case(Base):
    __tablename__ = "cases"

    # 添加复合索引用于地理查询优化
    __table_args__ = (
        Index('ix_cases_geo', 'latitude', 'longitude'),
        Index('ix_cases_status', 'status'),
        Index('ix_cases_occurred_time', 'occurred_time'),
    )

    id = Column(Integer, primary_key=True, index=True)
    case_number = Column(String(50), unique=True, nullable=False, index=True)
    occurred_time = Column(DateTime(timezone=True), nullable=False)
    location = Column(String(200))
    # 地理信息：经纬度，支持地图定位和空间分析（已添加复合索引）
    latitude = Column(Float, nullable=True, index=True)   # 纬度
    longitude = Column(Float, nullable=True, index=True)  # 经度
    case_type = Column(String(50))
    description = Column(Text)
    involved_persons = Column(JSON)
    involved_items = Column(JSON)
    loss_amount = Column(Integer)
    # 涉油案件专用字段（可为空，用于普通案件兼容）
    oil_type = Column(String(50))  # 油品类型：汽油/柴油/原油/润滑油等
    oil_volume = Column(Float)  # 涉油数量（吨/升，按统一单位约定）
    oil_value = Column(Integer)  # 估算价值（元）
    facility_type = Column(String(50))  # 目标设施类型：管线/油库/加油站/油罐车等
    facility_owner = Column(String(100))  # 设施所属单位/企业
    security_level = Column(String(50))  # 安防等级/薄弱程度标签
    modus_operandi = Column(String(200))  # 主要作案手法标签，如“打孔盗油”
    suspect_roles = Column(JSON)  # 嫌疑人角色列表：内部员工/司机/加油员等
    vehicle_info = Column(JSON)  # 车辆信息：车牌、类型、是否套牌等
    upstream_source = Column(String(200))  # 上游油品来源点
    downstream_destination = Column(String(200))  # 下游疑似销赃去向
    status = Column(String(20), default="pending")
    features = Column(JSON)  # AI提取的特征
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

