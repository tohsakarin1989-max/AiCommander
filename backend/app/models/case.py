from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, DateTime, Text, JSON, Float, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class Case(Base):
    __tablename__ = "cases"

    # 添加复合索引用于地理查询优化
    __table_args__ = (
        Index('ix_cases_geo', 'latitude', 'longitude'),
        Index('ix_cases_status', 'status'),
        Index('ix_cases_occurred_time', 'occurred_time'),
        Index('ix_cases_report_time', 'report_time'),
        Index('ix_cases_source_type', 'source_type'),
        Index('ix_cases_report_unit', 'report_unit'),
        Index('ix_cases_current_stage', 'current_stage'),
        Index('ix_cases_quality_level', 'quality_level'),
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
    # 保卫系统业务管理细则要求的报送、处置、质量字段
    report_time = Column(DateTime(timezone=True))  # 案件报送时间，校验 1 小时报送
    report_unit = Column(String(100))  # 报送/责任单位、保卫班
    source_type = Column(String(50))  # 线索来源：巡逻发现/群众举报/领导指派/公安机关线索等
    source_detail = Column(Text)  # 线索补充说明
    police_reported = Column(Boolean, default=False)  # 是否报案
    case_filed = Column(Boolean, default=False)  # 是否立案
    police_officer = Column(String(100))  # 公安出警人
    police_phone = Column(String(50))  # 公安出警联系电话
    security_officers = Column(JSON)  # 保卫班出警人员
    oil_nature = Column(String(50))  # 原油性质：被盗原油/落地原油等
    water_cut = Column(Float)  # 检斤含水率
    vehicle_handling = Column(String(100))  # 涉案车辆处理方式
    person_handling = Column(String(100))  # 抓获人员处理方式
    oil_handling = Column(String(100))  # 涉案原油处理方式
    operation_role = Column(String(50))  # 联合行动角色：主导/联合/配合/协助
    current_stage = Column(String(50), default="reported")  # 当前办理阶段
    quality_score = Column(Float)  # 案件信息质量评分
    quality_level = Column(String(20))  # high/medium/low
    quality_issues = Column(JSON)  # 评分明细、缺项、建议
    quality_updated_at = Column(DateTime(timezone=True))
    status = Column(String(20), default="pending")
    features = Column(JSON)  # AI提取的特征
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    vehicles = relationship("CaseVehicle", back_populates="case", cascade="all, delete-orphan")
    persons = relationship("CasePerson", back_populates="case", cascade="all, delete-orphan")
    evidence = relationship("CaseEvidence", back_populates="case", cascade="all, delete-orphan")
    oil_recovery_records = relationship("OilRecoveryRecord", back_populates="case", cascade="all, delete-orphan")
    tips = relationship("CaseTip", back_populates="case")


class CaseVehicle(Base):
    __tablename__ = "case_vehicles"
    __table_args__ = (
        Index("ix_case_vehicles_case_id", "case_id"),
        Index("ix_case_vehicles_plate_number", "plate_number"),
        Index("ix_case_vehicles_handling_status", "handling_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    vehicle_type = Column(String(50))
    color = Column(String(50))
    brand = Column(String(100))
    model = Column(String(100))
    plate_number = Column(String(50))
    oil_volume = Column(Float)
    water_cut = Column(Float)
    custody_location = Column(String(200))  # 扣押/停放地点
    current_location = Column(String(200))
    handling_status = Column(String(100))  # 扣押/移交公安/返还/待处理等
    transferred_to_police = Column(Boolean, default=False)
    transfer_time = Column(DateTime(timezone=True))
    transfer_document_no = Column(String(100))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    case = relationship("Case", back_populates="vehicles")


class CasePerson(Base):
    __tablename__ = "case_persons"
    __table_args__ = (
        Index("ix_case_persons_case_id", "case_id"),
        Index("ix_case_persons_name", "name"),
        Index("ix_case_persons_id_number", "id_number"),
    )

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    name = Column(String(100))
    gender = Column(String(20))
    id_number = Column(String(50))
    home_address = Column(String(300))
    phone = Column(String(50))
    role = Column(String(50))
    handling_status = Column(String(100))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    case = relationship("Case", back_populates="persons")


class CaseEvidence(Base):
    __tablename__ = "case_evidence"
    __table_args__ = (
        Index("ix_case_evidence_case_id", "case_id"),
        Index("ix_case_evidence_type", "evidence_type"),
        Index("ix_case_evidence_requirement", "requirement_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    evidence_type = Column(String(50))  # photo/rubbing/document/video/other
    title = Column(String(200))
    file_path = Column(String(500))
    requirement_key = Column(String(100))  # vehicle_front/vehicle_vin_rubbing 等标准项
    captured_at = Column(DateTime(timezone=True))
    latitude = Column(Float)
    longitude = Column(Float)
    is_sensitive = Column(Boolean, default=True)
    meta = Column(JSON)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    case = relationship("Case", back_populates="evidence")


class OilRecoveryRecord(Base):
    __tablename__ = "oil_recovery_records"
    __table_args__ = (
        Index("ix_oil_recovery_case_id", "case_id"),
        Index("ix_oil_recovery_oil_nature", "oil_nature"),
    )

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    oil_nature = Column(String(50))
    volume_tons = Column(Float)
    water_cut = Column(Float)
    source = Column(String(200))
    receiver = Column(String(200))
    handled_at = Column(DateTime(timezone=True))
    handling_method = Column(String(100))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    case = relationship("Case", back_populates="oil_recovery_records")


class CaseTip(Base):
    __tablename__ = "case_tips"
    __table_args__ = (
        Index("ix_case_tips_case_id", "case_id"),
        Index("ix_case_tips_reported_at", "reported_at"),
        Index("ix_case_tips_verification_status", "verification_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    reporter_name = Column(String(100))
    reporter_contact = Column(String(100))
    reported_at = Column(DateTime(timezone=True))
    location = Column(String(200))
    content = Column(Text)
    source_type = Column(String(50))
    verification_status = Column(String(50), default="pending")
    resolution = Column(Text)
    prevention_actions = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    case = relationship("Case", back_populates="tips")
