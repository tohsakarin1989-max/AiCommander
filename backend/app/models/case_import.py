"""Committed import receipts, scoped like the cases they describe."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func

from app.database import Base


class CaseImportBatch(Base):
    __tablename__ = "case_import_batches"

    id = Column(String(36), primary_key=True)
    input_hash = Column(String(64), nullable=False, unique=True)
    operational_area_id = Column(Integer, ForeignKey("operational_areas.id"), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CaseImportRow(Base):
    __tablename__ = "case_import_rows"
    __table_args__ = (UniqueConstraint("batch_id", "row_number", name="uq_case_import_rows_source"),)

    id = Column(Integer, primary_key=True)
    batch_id = Column(String(36), ForeignKey("case_import_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    operational_area_id = Column(Integer, ForeignKey("operational_areas.id"), nullable=True, index=True)
    row_number = Column(Integer, nullable=False)
    source_values = Column(JSON, nullable=False)
    current_values = Column(JSON, nullable=False)
    time_zone = Column(String(40), nullable=False, default="UTC")
    status = Column(String(20), nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="SET NULL"), nullable=True)
    error = Column(Text, nullable=True)
    revision = Column(Integer, nullable=False, default=0)
    corrections = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CaseImportTemplate(Base):
    """Immutable parsing configuration; never stores source case text."""
    __tablename__ = "case_import_templates"

    id = Column(String(36), primary_key=True)
    operational_area_id = Column(Integer, ForeignKey("operational_areas.id"), nullable=True, index=True)
    name = Column(String(80), nullable=False)
    settings = Column(JSON, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CaseImportSourceRecord(Base):
    """Source identity, not event identity; deleted target retains its tombstone."""
    __tablename__ = 'case_import_source_records'
    __table_args__ = (UniqueConstraint('operational_area_id', 'source_key', 'external_key',
                                       name='uq_case_import_source_identity'),)
    id = Column(Integer, primary_key=True)
    operational_area_id = Column(Integer, ForeignKey('operational_areas.id'), nullable=False, index=True)
    source_key = Column(String(80), nullable=False)
    external_key = Column(String(160), nullable=False)
    case_id = Column(Integer, ForeignKey('cases.id', ondelete='SET NULL'), nullable=True, index=True)
    source_version = Column(String(100), nullable=True)
    source_hash = Column(String(64), nullable=False)
    source_values = Column(JSON, nullable=False)
    adopted_values = Column(JSON, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    last_batch_id = Column(String(36), ForeignKey('case_import_batches.id'), nullable=False)
    last_row_number = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
