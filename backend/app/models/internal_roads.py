"""内部道路来源快照；不与正式点位或计算路网混用。"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class InternalRoadImport(Base):
    __tablename__ = "internal_road_imports"
    __table_args__ = (UniqueConstraint("source_id", "input_sha256", name="uq_internal_road_source_hash"),)

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("map_sources.id", ondelete="RESTRICT"), nullable=False, index=True)
    operational_area_id = Column(Integer, ForeignKey("operational_areas.id", ondelete="RESTRICT"), nullable=False, index=True)
    input_sha256 = Column(String(64), nullable=False)
    schema_version = Column(String(80), nullable=False)
    # 完整批次作为不可覆盖的来源版本，不将后续缺失记录解释成删除。
    features = Column(JSON, nullable=False)
    warnings = Column(JSON, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InternalRoadReview(Base):
    """只追加核验决定；决定绑定批次和要素，不能改变原始来源几何。"""
    __tablename__ = "internal_road_reviews"
    __table_args__ = (
        UniqueConstraint("import_id", "feature_id", "sequence", name="uq_road_review_sequence"),
        UniqueConstraint("import_id", "feature_id", "request_key", name="uq_road_review_request"),
    )

    id = Column(Integer, primary_key=True)
    import_id = Column(Integer, ForeignKey("internal_road_imports.id", ondelete="RESTRICT"), nullable=False, index=True)
    operational_area_id = Column(Integer, ForeignKey("operational_areas.id", ondelete="RESTRICT"), nullable=False, index=True)
    feature_id = Column(String(100), nullable=False)
    sequence = Column(Integer, nullable=False)
    request_key = Column(String(80), nullable=False)
    decision = Column(String(30), nullable=False)
    note = Column(String(2000), nullable=False)
    evidence_reference = Column(String(500), nullable=False)
    connection_evidence = Column(JSON, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InternalRoadFeatureVersion(Base):
    """批次要素索引，支持跨历史目录检索，不按名称合并。"""
    __tablename__ = "internal_road_feature_versions"
    __table_args__ = (UniqueConstraint("import_id", "feature_id", name="uq_internal_road_feature_version"),)
    id = Column(Integer, primary_key=True)
    import_id = Column(Integer, ForeignKey("internal_road_imports.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_id = Column(Integer, ForeignKey("map_sources.id", ondelete="RESTRICT"), nullable=False, index=True)
    operational_area_id = Column(Integer, ForeignKey("operational_areas.id", ondelete="RESTRICT"), nullable=False, index=True)
    feature_id = Column(String(100), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    kind = Column(String(20), nullable=False)
