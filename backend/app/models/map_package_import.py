"""Durable public package reception; never represents an accepted map bundle."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from app.database import Base


class MapPackageImport(Base):
    __tablename__ = 'map_package_imports'

    id = Column(String(36), primary_key=True)
    manifest_hash = Column(String(64), nullable=False, unique=True)
    manifest = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default='receiving', index=True)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    error_code = Column(String(80), nullable=True)
    report = Column(JSON, nullable=True)
    lease_token = Column(String(36), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MapPackageImportChunk(Base):
    __tablename__ = 'map_package_import_chunks'

    import_id = Column(String(36), ForeignKey('map_package_imports.id', ondelete='CASCADE'), primary_key=True)
    name = Column(String(110), primary_key=True)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False)
