"""态势简报、部署建议和技防聚合数据模型。"""
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class TechDefenseSource(Base):
    __tablename__ = "tech_defense_sources"
    __table_args__ = (
        UniqueConstraint("source_key", "operational_area_id", name="uq_tech_source_area"),
    )

    id = Column(Integer, primary_key=True)
    source_key = Column(String(100), nullable=False)
    name = Column(String(200), nullable=False)
    operational_area_id = Column(Integer, ForeignKey("operational_areas.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(30), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TechDefenseEventAggregate(Base):
    __tablename__ = "tech_defense_event_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "period_start",
            "period_end",
            "device_type",
            name="uq_tech_aggregate_period",
        ),
        Index("ix_tech_aggregate_area_period", "operational_area_id", "period_end"),
    )

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("tech_defense_sources.id", ondelete="CASCADE"), nullable=False)
    operational_area_id = Column(Integer, ForeignKey("operational_areas.id", ondelete="CASCADE"), nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    device_type = Column(String(50), nullable=False)
    online_count = Column(Integer, nullable=False, default=0)
    offline_count = Column(Integer, nullable=False, default=0)
    alert_count = Column(Integer, nullable=False, default=0)
    redacted_vehicle_event_count = Column(Integer, nullable=False, default=0)
    disposition_summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SituationBrief(Base):
    __tablename__ = "situation_briefs"
    __table_args__ = (
        UniqueConstraint("operational_area_id", "period_type", "input_fingerprint", name="uq_situation_brief_input"),
        Index("ix_situation_briefs_area_period", "operational_area_id", "period_type", "generated_at"),
    )

    id = Column(String(36), primary_key=True)
    operational_area_id = Column(Integer, ForeignKey("operational_areas.id", ondelete="CASCADE"), nullable=False)
    period_type = Column(String(20), nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    input_fingerprint = Column(String(64), nullable=False)
    status = Column(String(30), nullable=False)
    algorithm_version = Column(String(80), nullable=False, default="deployment-advisor-3.5.0")
    scope_policy_version = Column(String(80), nullable=False, default="area-scope-3.6.0")
    summary = Column(Text, nullable=False)
    evidence_refs = Column(JSON, nullable=False)
    information_gaps = Column(JSON, nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DeploymentRecommendation(Base):
    __tablename__ = "deployment_recommendations"
    __table_args__ = (
        UniqueConstraint("brief_id", "rank", name="uq_deployment_recommendation_rank"),
        Index("ix_deployment_recommendations_status", "status", "valid_until"),
    )

    id = Column(String(36), primary_key=True)
    brief_id = Column(String(36), ForeignKey("situation_briefs.id", ondelete="CASCADE"), nullable=False)
    rank = Column(Integer, nullable=False)
    title = Column(String(300), nullable=False)
    target_area = Column(String(300), nullable=False)
    time_window = Column(String(200), nullable=False)
    suggested_action = Column(Text, nullable=False)
    resource_assumption = Column(Text, nullable=False)
    expected_effect = Column(Text, nullable=False)
    evidence_refs = Column(JSON, nullable=False)
    supporting_evidence = Column(JSON, nullable=False)
    information_gaps = Column(JSON, nullable=False)
    confidence = Column(Float, nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(30), nullable=False, default="candidate")
    auto_execution_allowed = Column(Boolean, nullable=False, default=False)
    boundary = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RecommendationFeedback(Base):
    __tablename__ = "recommendation_feedback"
    __table_args__ = (
        Index("ix_recommendation_feedback_rec", "recommendation_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    recommendation_id = Column(
        String(36),
        ForeignKey("deployment_recommendations.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision = Column(String(40), nullable=False)
    usefulness_score = Column(Integer, nullable=True)
    note = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
