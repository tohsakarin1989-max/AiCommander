"""Immutable road calculation attachments; never overwrite frozen case reports."""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class CaseRoadArtifact(Base):
    __tablename__ = 'case_road_artifacts'
    __table_args__ = (
        UniqueConstraint('case_result_id', 'created_by', 'content_sha256', name='uq_case_road_artifact_content'),
        Index('ix_case_road_artifacts_history', 'case_result_id', 'created_at', 'id'),
    )
    id = Column(String(36), primary_key=True)
    case_id = Column(Integer, ForeignKey('cases.id', ondelete='CASCADE'), nullable=False)
    case_result_id = Column(String(36), ForeignKey('case_result_snapshots.id', ondelete='CASCADE'), nullable=False)
    network_id = Column(String(36), ForeignKey('road_network_versions.id', ondelete='RESTRICT'), nullable=False)
    operation = Column(String(20), nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    content = Column(JSON, nullable=False)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
