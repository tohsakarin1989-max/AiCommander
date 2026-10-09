"""Scope-bound output configuration; no source case text or executable expressions."""
from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey, CheckConstraint, func
from app.database import Base


class OutputTemplate(Base):
    __tablename__ = 'output_templates'
    __table_args__ = (CheckConstraint("kind IN ('case_ledger','material_sections')", name='ck_output_template_kind'),)
    id = Column(String(36), primary_key=True)
    operational_area_id = Column(Integer, ForeignKey('operational_areas.id'), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    kind = Column(String(30), nullable=False)
    name = Column(String(80), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    configuration = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
