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
