"""
巡逻记录模型
用于记录巡逻执行情况，形成反馈闭环
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class PatrolRecord(Base):
    """巡逻记录"""
    __tablename__ = "patrol_records"

    id = Column(Integer, primary_key=True, index=True)
    # 巡逻基本信息
    patrol_number = Column(String(50), unique=True, index=True)  # 巡逻编号
    patrol_type = Column(String(50))  # 巡逻类型：routine/targeted/emergency
    area_name = Column(String(200))  # 巡逻区域名称
    area_coordinates = Column(JSON)  # 区域坐标（多边形）

    # 执行信息
    start_time = Column(DateTime)  # 开始时间
    end_time = Column(DateTime)  # 结束时间
    patrol_route = Column(JSON)  # 巡逻路线轨迹
    officer_count = Column(Integer, default=1)  # 巡逻人数
    officer_names = Column(String(500))  # 巡逻人员姓名

    # 结果记录
    status = Column(String(50), default="planned")  # planned/in_progress/completed/cancelled
    findings = Column(Text)  # 巡逻发现
    issues_found = Column(Integer, default=0)  # 发现问题数量
    actions_taken = Column(Text)  # 采取的措施
    evidence_photos = Column(JSON)  # 证据照片URL列表

    # 关联信息
    related_case_ids = Column(JSON)  # 相关案件ID
    related_deployment_id = Column(Integer)  # 关联的工作部署建议ID

    # 反馈评估
    risk_before = Column(Float)  # 巡逻前风险评分
    risk_after = Column(Float)  # 巡逻后风险评分
    effectiveness_score = Column(Float)  # 巡逻效果评分（0-100）
    feedback_notes = Column(Text)  # 反馈备注

    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String(100))  # 创建人


class AreaRiskAssessment(Base):
    """区域风险评估记录"""
    __tablename__ = "area_risk_assessments"

    id = Column(Integer, primary_key=True, index=True)
    area_name = Column(String(200), index=True)  # 区域名称
    area_coordinates = Column(JSON)  # 区域坐标

    # 风险评分
    risk_score = Column(Float, default=0)  # 当前风险评分（0-100）
    risk_level = Column(String(20))  # 风险等级：low/medium/high/critical

    # 评分因素
    case_count_30d = Column(Integer, default=0)  # 30天内案件数
    case_count_7d = Column(Integer, default=0)  # 7天内案件数
    patrol_count_30d = Column(Integer, default=0)  # 30天内巡逻次数
    last_patrol_date = Column(DateTime)  # 最后巡逻日期
    days_since_patrol = Column(Integer)  # 距上次巡逻天数

    # 历史记录
    risk_history = Column(JSON)  # 风险评分历史 [{date, score, reason}]

    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
