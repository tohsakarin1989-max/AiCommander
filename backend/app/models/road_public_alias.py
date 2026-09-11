"""Append-only reviewed correspondence; never grants traversal permission."""
from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class RoadPublicAlias(Base):
    __tablename__ = 'road_public_aliases'
    id = Column(Integer, primary_key=True)
    import_id = Column(Integer, ForeignKey('internal_road_imports.id', ondelete='RESTRICT'), nullable=False)
    feature_id = Column(String(100), nullable=False)
    operational_area_id = Column(Integer, ForeignKey('operational_areas.id', ondelete='RESTRICT'), nullable=False, index=True)
    public_source_sha256 = Column(String(64), nullable=False)
    osm_way_id = Column(BigInteger, nullable=False)
    sequence = Column(Integer, nullable=False)
    decision = Column(String(20), nullable=False)
    request_key = Column(String(80), nullable=False)
    evidence_reference = Column(String(500), nullable=False)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint('import_id', 'feature_id', 'public_source_sha256', 'osm_way_id', 'sequence', name='uq_road_public_alias_sequence'),
        UniqueConstraint('import_id', 'request_key', name='uq_road_public_alias_request'),
        CheckConstraint("decision IN ('verified', 'revoked')", name='ck_road_public_alias_decision'),
        CheckConstraint('osm_way_id > 0 AND sequence > 0', name='ck_road_public_alias_positive'),
    )
