"""v3.6 算法、授权策略和脱敏评测版本对象。"""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class AlgorithmVersion(Base):
    __tablename__ = "algorithm_versions"
    __table_args__ = (
        UniqueConstraint("component", "version", name="uq_algorithm_component_version"),
    )

    id = Column(Integer, primary_key=True)
    component = Column(String(80), nullable=False)
    version = Column(String(80), nullable=False)
    configuration = Column(JSON, nullable=False)
    checksum = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ScopePolicyVersion(Base):
    __tablename__ = "scope_policy_versions"

    id = Column(Integer, primary_key=True)
    version = Column(String(80), nullable=False, unique=True)
    policy = Column(JSON, nullable=False)
    checksum = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EvaluationDataset(Base):
    __tablename__ = "evaluation_datasets"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_evaluation_dataset_version"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    version = Column(String(80), nullable=False)
    classification = Column(String(30), nullable=False)
    case_ids = Column(JSON, nullable=False)
    ground_truth = Column(JSON, nullable=False)
    manifest = Column(JSON, nullable=False)
    checksum = Column(String(64), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        Index("ix_evaluation_runs_dataset_status", "dataset_id", "status"),
    )

    id = Column(String(36), primary_key=True)
    dataset_id = Column(Integer, ForeignKey("evaluation_datasets.id", ondelete="RESTRICT"), nullable=False)
    algorithm_manifest = Column(JSON, nullable=False)
    scope_policy_version = Column(String(80), nullable=False)
    status = Column(String(30), nullable=False)
    metrics = Column(JSON, nullable=False)
    trace_manifest = Column(JSON, nullable=False)
    failure_reason = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
