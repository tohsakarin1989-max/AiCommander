"""
事件数据模型
用于记录各类发现情况（比案件更宽泛），支持关联分析和区域研判
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Float, Boolean, Index, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


# 事件类型定义
EVENT_TYPES = {
    "theft_case": "盗油案件",           # 已破获的盗油案
    "vehicle_caught": "查获车辆",        # 抓获的盗油/运油车辆
    "stash_found": "发现囤油点",         # 发现的非法囤油点
    "equipment_found": "发现作案工具",   # 发现的打孔设备等
    "suspect_activity": "可疑活动",      # 巡逻中发现的可疑情况
    "damage_found": "发现设施损坏",      # 发现的盗油痕迹/管线损坏
    "illegal_station": "非法加油站",     # 发现的黑加油站
    "pipeline_tap": "管线打孔点",        # 发现的管线盗油点
}


# 关联类型定义
RELATION_TYPES = {
    "spatial_cluster": {
        "name": "空间聚集",
        "description": "多个事件发生在同一区域",
        "implication": "该区域可能是作案团伙的活动范围"
    },
    "supply_chain": {
        "name": "上下游关联",
        "description": "盗油点→运输→囤油点的链条关系",
        "implication": "可顺藤摸瓜，从一个环节推断其他环节"
    },
    "temporal_pattern": {
        "name": "时间规律",
        "description": "同一区域周期性发案",
        "implication": "可能是固定团伙定期作案"
    },
    "modus_match": {
        "name": "手法相似",
        "description": "多个事件使用相同/相似作案手法",
        "implication": "可能是同一团伙或同一师承"
    },
    "vehicle_link": {
        "name": "车辆关联",
        "description": "涉及相同车辆或同类型车辆",
        "implication": "可能是同一团伙使用的车辆"
    },
    "route_pattern": {
        "name": "路线关联",
        "description": "事件分布沿特定道路/管线",
        "implication": "该路线可能是作案团伙的惯用路线"
    }
}


class Event(Base):
    """
    事件记录（比案件更宽泛，包括各类发现情况）
    """
    __tablename__ = "events"

    __table_args__ = (
        Index('ix_events_geo', 'latitude', 'longitude'),
        Index('ix_events_village', 'village_name'),
        Index('ix_events_type_time', 'event_type', 'occurred_time'),
    )

    id = Column(Integer, primary_key=True, index=True)
    event_number = Column(String(50), unique=True, nullable=False, index=True)  # 事件编号
    event_type = Column(String(50), nullable=False, index=True)  # 事件类型

    # 时空信息
    occurred_time = Column(DateTime(timezone=True), nullable=False)  # 发生/发现时间
    location = Column(String(200))  # 地点描述
    latitude = Column(Float, index=True)  # 纬度
    longitude = Column(Float, index=True)  # 经度

    # 关联的村屯/区域（用于区域聚合分析）
    village_name = Column(String(100), index=True)  # 最近村屯名称
    village_distance_km = Column(Float)  # 距村屯中心距离（公里）
    township = Column(String(100))  # 所属乡镇

    # 事件详情
    title = Column(String(200))  # 事件标题/简述
    description = Column(Text)  # 详细描述

    # 涉及对象
    vehicles = Column(JSON)  # 涉及车辆 [{"plate": "...", "type": "面包车", "color": "白色"}]
    oil_volume_liters = Column(Float)  # 涉及油量（升）
    oil_type = Column(String(50))  # 油品类型
    equipment = Column(JSON)  # 涉及设备/工具 ["电钻", "软管", "油桶"]
    suspects_count = Column(Integer)  # 涉及人数
    suspects_description = Column(Text)  # 人员特征描述（脱敏）

    # 处置信息
    discovery_method = Column(String(50))  # 发现方式：巡逻发现/群众举报/其他
    handling_result = Column(String(100))  # 处置结果：移交公安/内部处理/持续关注

    # 关联案件（如果由案件转化而来）
    related_case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    related_case = relationship("Case", backref="events")

    # 研判标记
    is_analyzed = Column(Boolean, default=False)  # 是否已纳入研判
    risk_level = Column(String(20))  # 风险等级：low/medium/high
    analysis_notes = Column(Text)  # 研判备注
    suggested_actions = Column(JSON)  # 建议行动

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(String(50))  # 录入人


class AreaProfile(Base):
    """
    区域档案（以村屯/区域为单位的聚合分析）
    用于区域研判和风险评估
    """
    __tablename__ = "area_profiles"

    __table_args__ = (
        Index('ix_area_geo', 'center_latitude', 'center_longitude'),
        Index('ix_area_risk', 'risk_level'),
    )

    id = Column(Integer, primary_key=True, index=True)
    area_name = Column(String(100), unique=True, nullable=False, index=True)  # 村屯/区域名称
    area_type = Column(String(50), default="village")  # 区域类型：village/township/custom

    # 地理信息
    center_latitude = Column(Float)  # 中心点纬度
    center_longitude = Column(Float)  # 中心点经度
    radius_km = Column(Float, default=5.0)  # 关联范围（公里）
    boundary = Column(JSON)  # 边界多边形坐标（可选）

    # 所属行政区划
    township = Column(String(100))  # 所属乡镇
    county = Column(String(100))  # 所属县区

    # 统计数据（定期更新）
    total_events = Column(Integer, default=0)  # 事件总数
    events_last_30_days = Column(Integer, default=0)  # 近30天事件数
    events_last_90_days = Column(Integer, default=0)  # 近90天事件数
    first_event_time = Column(DateTime(timezone=True))  # 首次事件时间
    last_event_time = Column(DateTime(timezone=True))  # 最近事件时间
    event_types_count = Column(JSON)  # 事件类型统计 {"theft_case": 2, "stash_found": 1}

    # 风险评估
    risk_level = Column(String(20), default="low")  # 风险等级：low/medium/high/critical
    risk_score = Column(Float, default=0)  # 风险分数 0-100
    risk_factors = Column(JSON)  # 风险因素列表
    risk_updated_at = Column(DateTime(timezone=True))  # 风险评估更新时间

    # 研判结论
    assessment = Column(Text)  # AI 研判结论
    suggested_actions = Column(JSON)  # 建议行动列表
    patrol_suggestions = Column(JSON)  # 巡逻建议
    watch_targets = Column(JSON)  # 重点关注目标

    # 关联信息
    related_areas = Column(JSON)  # 关联的其他区域（可能是同一团伙活动范围）

    # 状态
    is_active = Column(Boolean, default=True)  # 是否活跃关注
    last_patrol_time = Column(DateTime(timezone=True))  # 最后巡逻时间

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class EventRelation(Base):
    """
    事件之间的关联关系
    用于记录和分析事件之间的联系
    """
    __tablename__ = "event_relations"

    __table_args__ = (
        Index('ix_relation_events', 'event_a_id', 'event_b_id'),
        Index('ix_relation_type', 'relation_type'),
    )

    id = Column(Integer, primary_key=True, index=True)

    # 关联的两个事件
    event_a_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    event_b_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    event_a = relationship("Event", foreign_keys=[event_a_id], backref="relations_as_a")
    event_b = relationship("Event", foreign_keys=[event_b_id], backref="relations_as_b")

    # 关联信息
    relation_type = Column(String(50), nullable=False)  # 关联类型
    confidence = Column(Float, default=0.5)  # 关联置信度 0-1
    distance_km = Column(Float)  # 空间距离（公里）
    time_gap_days = Column(Integer)  # 时间间隔（天）
    evidence = Column(Text)  # 关联依据说明
    reasoning = Column(Text)  # 推理说明

    # 确认状态
    is_system_generated = Column(Boolean, default=True)  # 是否系统自动生成
    is_confirmed = Column(Boolean, default=False)  # 是否人工确认
    confirmed_by = Column(String(50))  # 确认人
    confirmed_at = Column(DateTime(timezone=True))  # 确认时间
    is_rejected = Column(Boolean, default=False)  # 是否被否定

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AnalysisSession(Base):
    """
    研判会话（替代原有的会议概念，更聚焦于区域研判）
    """
    __tablename__ = "analysis_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_number = Column(String(50), unique=True, nullable=False, index=True)

    # 研判类型
    analysis_type = Column(String(50), nullable=False)  # area_analysis/pattern_analysis/patrol_review
    title = Column(String(200))  # 研判主题

    # 研判对象
    target_area_id = Column(Integer, ForeignKey("area_profiles.id"), nullable=True)
    target_area = relationship("AreaProfile", backref="analysis_sessions")
    target_event_ids = Column(JSON)  # 涉及的事件ID列表

    # 研判上下文
    context = Column(JSON)  # 研判上下文数据（统计、关联等）
    questions = Column(JSON)  # 研判问题列表

    # 研判结果
    status = Column(String(20), default="pending")  # pending/in_progress/completed
    findings = Column(JSON)  # 发现的问题/规律
    conclusions = Column(Text)  # 研判结论
    recommendations = Column(JSON)  # 行动建议

    # 专家分析
    analyst_responses = Column(JSON)  # 各专家的分析结果
    consensus_points = Column(JSON)  # 共识点
    divergence_points = Column(JSON)  # 分歧点

    # 时间信息
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(String(50))
