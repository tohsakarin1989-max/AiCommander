"""Disposable material metadata and explicit references, never facts or ACLs."""
from sqlalchemy import Column, DateTime, ForeignKeyConstraint, Index, String
from sqlalchemy.sql import func

from app.database import Base


class ResultCatalogProjection(Base):
    __tablename__ = 'result_catalog_projections'
    __table_args__ = (
        Index('ix_result_catalog_checked', 'checked_at', 'material_kind', 'material_id'),
        Index('ix_result_catalog_subject', 'subject_kind', 'subject_id', 'material_created_at'),
    )
    material_kind = Column(String(24), primary_key=True)
    material_id = Column(String(80), primary_key=True)
    title = Column(String(240), nullable=True)
    material_created_at = Column(DateTime(timezone=True), nullable=True)
    subject_kind = Column(String(24), nullable=True)
    subject_id = Column(String(80), nullable=True)
    # Some legacy stores derive the digest at read time. Never invent one.
    content_sha256 = Column(String(64), nullable=True)
    schema_version = Column(String(80), nullable=True)
    algorithm_version = Column(String(80), nullable=False)
    source_sha256 = Column(String(64), nullable=True)
    state = Column(String(24), nullable=False)
    checked_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ResultCatalogReference(Base):
    __tablename__ = 'result_catalog_references'
    __table_args__ = (
        ForeignKeyConstraint(['material_kind', 'material_id'],
                             ['result_catalog_projections.material_kind', 'result_catalog_projections.material_id'],
                             ondelete='CASCADE'),
        Index('ix_result_catalog_reference', 'reference_kind', 'reference_id'),
    )
    material_kind = Column(String(24), primary_key=True)
    material_id = Column(String(80), primary_key=True)
    reference_kind = Column(String(32), primary_key=True)
    reference_id = Column(String(120), primary_key=True)
    relation = Column(String(80), primary_key=True)
    expected_version = Column(String(128), primary_key=True, default='')
