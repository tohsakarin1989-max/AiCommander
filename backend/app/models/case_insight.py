"""案件—地图自动融合研判的运行、候选与反馈模型。"""
from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class CaseAnalysisRun(Base):
    __tablename__ = "case_analysis_runs"
    __table_args__ = (
        UniqueConstraint(
            "case_profile_id",
            "map_snapshot_id",
            "algorithm_version",
            name="uq_case_analysis_input_version",
        ),
        Index("ix_case_analysis_case_status", "case_id", "status"),
    )

    id = Column(String(36), primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    case_profile_id = Column(
        String(36),
        ForeignKey("case_analysis_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    map_snapshot_id = Column(
        String(36),
        ForeignKey("map_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    algorithm_version = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False)
    summary = Column(Text, nullable=True)
    information_gaps = Column(JSON, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class CaseHypothesis(Base):
    __tablename__ = "case_hypotheses"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "rank", name="uq_case_hypothesis_rank"),
        Index("ix_case_hypotheses_case_type", "case_id", "hypothesis_type"),
    )

    id = Column(String(36), primary_key=True)
    analysis_run_id = Column(
        String(36),
        ForeignKey("case_analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    hypothesis_type = Column(String(40), nullable=False)
    rank = Column(Integer, nullable=False)
    title = Column(String(300), nullable=False)
    claim = Column(Text, nullable=False)
    score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    region = Column(JSON, nullable=True)
    evidence_refs = Column(JSON, nullable=False)
    supporting_evidence = Column(JSON, nullable=False)
    counter_evidence = Column(JSON, nullable=False)
    information_gaps = Column(JSON, nullable=False)
    score_components = Column(JSON, nullable=False)
    status = Column(String(30), nullable=False, default="candidate")
    boundary = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class HypothesisFeedback(Base):
    __tablename__ = "hypothesis_feedback"
    __table_args__ = (
        Index("ix_hypothesis_feedback_hypothesis", "hypothesis_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    hypothesis_id = Column(
        String(36),
        ForeignKey("case_hypotheses.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision = Column(String(30), nullable=False)
    note = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
