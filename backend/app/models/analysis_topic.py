"""Saved conditions and immutable derived snapshots, never copies of case records."""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class AnalysisTopic(Base):
    __tablename__ = 'analysis_topics'
    __table_args__ = (
        Index('ix_analysis_topics_owner', 'created_by', 'created_at', 'id'),
        Index('ix_analysis_topics_due', 'paused', 'refresh_state', 'next_refresh_at'),
    )
    id = Column(String(36), primary_key=True)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    title = Column(String(120), nullable=False)
    notes = Column(Text, nullable=False, default='')
    filters = Column(JSON, nullable=False)
    question = Column(Text, nullable=False, default='')
    question_kind = Column(String(40), nullable=False, default='condition_changes')
    window = Column(JSON, nullable=False, default=lambda: {'mode': 'fixed'})
    source_context = Column(JSON, nullable=True)
    definition_revision = Column(Integer, nullable=False, default=1)
    requested_generation = Column(Integer, nullable=False, default=1)
    last_data_revision = Column(Integer, nullable=False, default=-1)
    latest_job_id = Column(String(36), nullable=True)
    scope_version = Column(String(64), nullable=False)
    paused = Column(Boolean, nullable=False, default=False)
    refresh_state = Column(String(24), nullable=False, default='queued')
    lease_token = Column(String(36), nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    next_refresh_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_error = Column(String(80), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class TopicSnapshot(Base):
    __tablename__ = 'topic_snapshots'
    __table_args__ = (
        UniqueConstraint('topic_id', 'revision', name='uq_topic_snapshot_revision'),
        Index('ix_topic_snapshot_history', 'topic_id', 'revision'),
    )
    id = Column(String(36), primary_key=True)
    topic_id = Column(String(36), ForeignKey('analysis_topics.id', ondelete='CASCADE'), nullable=False)
    revision = Column(Integer, nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    changes = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TopicDefinitionRevision(Base):
    __tablename__ = 'topic_definition_revisions'
    __table_args__ = (UniqueConstraint('topic_id', 'revision', name='uq_topic_definition_revision'),)
    id = Column(String(36), primary_key=True)
    topic_id = Column(String(36), ForeignKey('analysis_topics.id', ondelete='CASCADE'), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TopicDependency(Base):
    __tablename__ = 'topic_dependencies'
    __table_args__ = (Index('ix_topic_dependency_source', 'kind', 'object_id'),)
    id = Column(String(36), primary_key=True)
    topic_id = Column(String(36), ForeignKey('analysis_topics.id', ondelete='CASCADE'), nullable=False, index=True)
    snapshot_id = Column(String(36), ForeignKey('topic_snapshots.id', ondelete='CASCADE'), nullable=False)
    kind = Column(String(50), nullable=False)
    object_id = Column(String(100), nullable=False)
    source_version = Column(String(100), nullable=True)


class TopicDataRevision(Base):
    """Conservative publication fence, not a data access grant or business count."""
    __tablename__ = 'topic_data_revision'
    id = Column(Integer, primary_key=True)
    revision = Column(Integer, nullable=False, default=0)


class TopicRefreshChunk(Base):
    """Bounded durable chunks; a killed worker never loses completed input work."""
    __tablename__ = 'topic_refresh_chunks'
    __table_args__ = (UniqueConstraint('job_id', 'phase', 'sequence', name='uq_topic_refresh_chunk'),)
    id = Column(String(36), primary_key=True)
    job_id = Column(String(36), ForeignKey('outbox_events.id', ondelete='CASCADE'), nullable=False, index=True)
    phase = Column(String(30), nullable=False)
    sequence = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
