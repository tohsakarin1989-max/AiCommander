"""受控 Agent 运行、事件、成果物与审批模型。"""
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from uuid import uuid4

from app.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_status_created", "status", "created_at"),
        Index("ix_agent_runs_created_by", "created_by"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_type = Column(String(50), nullable=False, index=True)
    query = Column(Text, nullable=False)
    case_ids = Column(JSON, nullable=False, default=list)
    asset_ids = Column(JSON, nullable=False, default=list)
    mode = Column(String(20), nullable=False, default="shadow")
    status = Column(String(30), nullable=False, default="queued", index=True)
    model_provider = Column(String(50), nullable=True)
    model_name = Column(String(100), nullable=True)
    data_version = Column(String(64), nullable=False)
    input_payload = Column(JSON, nullable=False, default=dict)
    result_summary = Column(JSON, nullable=False, default=dict)
    runtime_state = Column(JSON, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    replay_of_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    events = relationship(
        "AgentEvent",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentEvent.sequence",
    )
    artifacts = relationship(
        "AgentArtifact",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentArtifact.created_at",
    )
    approvals = relationship(
        "AgentApproval",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentApproval.created_at",
    )


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_agent_events_run_sequence"),
        Index("ix_agent_events_run_created", "run_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(60), nullable=False, index=True)
    status = Column(String(30), nullable=True)
    actor_type = Column(String(30), nullable=False, default="system")
    actor_name = Column(String(100), nullable=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    input_summary = Column(JSON, nullable=False, default=dict)
    output_summary = Column(JSON, nullable=False, default=dict)
    evidence_refs = Column(JSON, nullable=False, default=list)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    run = relationship("AgentRun", back_populates="events")


class AgentArtifact(Base):
    __tablename__ = "agent_artifacts"
    __table_args__ = (
        UniqueConstraint("run_id", "artifact_type", "version", name="uq_agent_artifact_version"),
        Index("ix_agent_artifacts_run_type", "run_id", "artifact_type"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    artifact_type = Column(String(50), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    content = Column(JSON, nullable=False, default=dict)
    evidence_refs = Column(JSON, nullable=False, default=list)
    source_signature = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    run = relationship("AgentRun", back_populates="artifacts")


class AgentApproval(Base):
    __tablename__ = "agent_approvals"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_agent_approvals_idempotency"),
        Index("ix_agent_approvals_run_status", "run_id", "status"),
        Index("ix_agent_approvals_expires_at", "expires_at"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    artifact_id = Column(String(36), ForeignKey("agent_artifacts.id", ondelete="CASCADE"), nullable=False)
    action_type = Column(String(50), nullable=False)
    target_type = Column(String(50), nullable=False)
    target_id = Column(Integer, nullable=False)
    candidate_patch = Column(JSON, nullable=False, default=dict)
    source_signature = Column(String(64), nullable=False)
    status = Column(String(30), nullable=False, default="pending", index=True)
    requested_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decision_comment = Column(Text, nullable=True)
    idempotency_key = Column(String(64), nullable=False)
    execution_result = Column(JSON, nullable=False, default=dict)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    run = relationship("AgentRun", back_populates="approvals")
