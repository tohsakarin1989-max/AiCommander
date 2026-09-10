"""案件零操作治理流水线模型。"""
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class OutboxEvent(Base):
    """与业务写入同事务提交的可靠事件。"""

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_status_available", "status", "available_at"),
    )

    id = Column(String(36), primary_key=True)
    event_type = Column(String(100), nullable=False)
    aggregate_type = Column(String(50), nullable=False)
    aggregate_id = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False)
    idempotency_key = Column(String(64), nullable=False, unique=True)
    status = Column(String(30), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    worker_id = Column(String(64), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CasePipelineState(Base):
    """每个案件当前治理状态。"""

    __tablename__ = "case_pipeline_states"

    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    status = Column(String(30), nullable=False, default="pending")
    source_hash = Column(String(64), nullable=False)
    event_id = Column(String(36), ForeignKey("outbox_events.id", ondelete="SET NULL"), nullable=True)
    schema_version = Column(String(30), nullable=False)
    dictionary_version = Column(String(30), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())


class CaseAnalysisProfile(Base):
    """不改写案件原文的版本化标准分析画像。"""

    __tablename__ = "case_analysis_profiles"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "source_hash",
            "schema_version",
            "dictionary_version",
            name="uq_case_profile_input_version",
        ),
        Index("ix_case_profiles_current", "case_id", "is_current"),
    )

    id = Column(String(36), primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    profile_version = Column(Integer, nullable=False)
    source_hash = Column(String(64), nullable=False)
    schema_version = Column(String(30), nullable=False)
    dictionary_version = Column(String(30), nullable=False)
    payload = Column(JSON, nullable=False)
    quality_score = Column(Float, nullable=False)
    analysis_readiness = Column(String(30), nullable=False)
    is_current = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
