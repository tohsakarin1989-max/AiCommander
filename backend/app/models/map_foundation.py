"""生产地图治理的来源、模板、批次与追溯模型。"""
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base


class OperationalArea(Base):
    """厂区或辖区，是案件与地图数据授权、分析的共同范围。"""

    __tablename__ = "operational_areas"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(100), nullable=False, unique=True, index=True)
    name = Column(String(200), nullable=False)
    boundary = Column(JSON, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="active", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class UserAreaScope(Base):
    """用户可读取或管理的厂区范围。"""

    __tablename__ = "user_area_scopes"
    __table_args__ = (
        UniqueConstraint("user_id", "operational_area_id", name="uq_user_area_scope"),
        Index("ix_user_area_scope_area_access", "operational_area_id", "access_level"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    operational_area_id = Column(
        Integer,
        ForeignKey("operational_areas.id", ondelete="CASCADE"),
        nullable=False,
    )
    access_level = Column(String(20), nullable=False, default="read")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MapSource(Base):
    """地图数据来源目录。"""

    __tablename__ = "map_sources"
    __table_args__ = (
        Index("ix_map_sources_area_status", "operational_area_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    source_key = Column(String(100), nullable=False, unique=True, index=True)
    name = Column(String(200), nullable=False)
    source_type = Column(String(50), nullable=False)
    trust_rank = Column(Integer, nullable=False, default=50)
    operational_area_id = Column(
        Integer,
        ForeignKey("operational_areas.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status = Column(String(20), nullable=False, default="active")
    description = Column(Text, nullable=True)
    configuration = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class MapImportTemplate(Base):
    """某一数据来源经过人工确认的表格字段与坐标转换模板。"""

    __tablename__ = "map_import_templates"
    __table_args__ = (
        UniqueConstraint("source_id", "name", "version", name="uq_map_template_version"),
        Index("ix_map_templates_source_active", "source_id", "is_active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("map_sources.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    sheet_name = Column(String(200), nullable=True)
    header_row = Column(Integer, nullable=False, default=1)
    field_mapping = Column(JSON, nullable=False)
    coordinate_system = Column(String(50), nullable=False)
    axis_order = Column(String(20), nullable=False, default="lon_lat")
    coordinate_unit = Column(String(20), nullable=False, default="degree")
    transformation = Column(JSON, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class MapIngestRun(Base):
    """一次可重放、可审计的地图数据导入批次。"""

    __tablename__ = "map_ingest_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_map_ingest_idempotency"),
        Index("ix_map_ingest_source_status", "source_id", "status"),
    )

    id = Column(String(36), primary_key=True)
    source_id = Column(Integer, ForeignKey("map_sources.id", ondelete="RESTRICT"), nullable=False)
    template_id = Column(
        Integer,
        ForeignKey("map_import_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status = Column(String(30), nullable=False, default="running")
    filename = Column(String(255), nullable=False)
    source_revision = Column(String(200), nullable=False, default="unspecified")
    file_hash = Column(String(64), nullable=False)
    idempotency_key = Column(String(64), nullable=False)
    total_rows = Column(Integer, nullable=False, default=0)
    valid_rows = Column(Integer, nullable=False, default=0)
    quarantined_rows = Column(Integer, nullable=False, default=0)
    created_assets = Column(Integer, nullable=False, default=0)
    updated_assets = Column(Integer, nullable=False, default=0)
    errors = Column(JSON, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class MapFeatureClaim(Base):
    """源文件中每一行对标准地图要素的声明；异常行也必须保留。"""

    __tablename__ = "map_feature_claims"
    __table_args__ = (
        UniqueConstraint("run_id", "row_number", name="uq_map_claim_run_row"),
        Index("ix_map_claims_source_status", "source_id", "status"),
        Index("ix_map_claims_asset", "asset_id"),
    )

    id = Column(Integer, primary_key=True)
    run_id = Column(String(36), ForeignKey("map_ingest_runs.id", ondelete="CASCADE"), nullable=False)
    source_id = Column(Integer, ForeignKey("map_sources.id", ondelete="RESTRICT"), nullable=False)
    row_number = Column(Integer, nullable=False)
    source_record_id = Column(String(200), nullable=True)
    source_revision = Column(String(200), nullable=False)
    raw_payload = Column(JSON, nullable=False)
    normalized_payload = Column(JSON, nullable=True)
    raw_hash = Column(String(64), nullable=False)
    status = Column(String(30), nullable=False)
    error_code = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    asset_id = Column(Integer, ForeignKey("jurisdiction_assets.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class JurisdictionAssetVersion(Base):
    """标准地图要素的不可变历史版本。"""

    __tablename__ = "jurisdiction_asset_versions"
    __table_args__ = (
        UniqueConstraint("asset_id", "version", name="uq_jurisdiction_asset_version"),
        Index("ix_asset_versions_claim", "source_claim_id"),
    )

    id = Column(Integer, primary_key=True)
    asset_id = Column(
        Integer,
        ForeignKey("jurisdiction_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    version = Column(Integer, nullable=False)
    source_claim_id = Column(
        Integer,
        ForeignKey("map_feature_claims.id", ondelete="SET NULL"),
        nullable=True,
    )
    snapshot = Column(JSON, nullable=False)
    change_type = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PublicMapBundle(Base):
    """联网区生成、经校验后导入内网的公共地图更新包。"""

    __tablename__ = "public_map_bundles"

    id = Column(Integer, primary_key=True, index=True)
    bundle_id = Column(String(200), nullable=False, unique=True, index=True)
    provider = Column(String(512), nullable=False)
    source_version = Column(String(512), nullable=False)
    license_record = Column(String(512), nullable=False)
    bounds = Column(JSON, nullable=False)
    manifest = Column(JSON, nullable=False)
    package_hash = Column(String(64), nullable=False, unique=True)
    status = Column(String(30), nullable=False, default="accepted", index=True)
    imported_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    imported_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MapSnapshot(Base):
    """公共底图与内网生产要素绑定后的统一地图版本。"""

    __tablename__ = "map_snapshots"
    __table_args__ = (
        Index("ix_map_snapshots_area_status", "operational_area_id", "status"),
    )

    id = Column(String(36), primary_key=True)
    version = Column(String(1024), nullable=False, unique=True, index=True)
    operational_area_id = Column(
        Integer,
        ForeignKey("operational_areas.id", ondelete="RESTRICT"),
        nullable=False,
    )
    public_bundle_id = Column(
        Integer,
        ForeignKey("public_map_bundles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status = Column(String(30), nullable=False, default="building")
    manifest = Column(JSON, nullable=False)
    feature_watermark = Column(String(100), nullable=False)
    built_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    built_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)
    superseded_at = Column(DateTime(timezone=True), nullable=True)


class MapSnapshotFeature(Base):
    """随地图快照冻结的生产与业务要素，发布后不再改写。"""

    __tablename__ = "map_snapshot_features"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "asset_id", name="uq_map_snapshot_asset"),
        Index("ix_map_snapshot_features_type", "snapshot_id", "asset_type"),
        Index("ix_map_snapshot_features_area", "operational_area_id", "snapshot_id"),
    )

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(
        String(36),
        ForeignKey("map_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    operational_area_id = Column(
        Integer,
        ForeignKey("operational_areas.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # 这里刻意不建立外键：快照必须在源要素/版本被清理后仍保留原始编号，
    # 否则历史证据引用会因 ON DELETE SET NULL 失去可复现性。
    asset_id = Column(Integer, nullable=False)
    asset_version_id = Column(Integer, nullable=True)
    name = Column(String(255), nullable=False)
    asset_type = Column(String(50), nullable=False)
    geometry_type = Column(String(50), nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    geometry = Column(JSON, nullable=True)
    source = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False)
    verified = Column(Boolean, nullable=False)
    verification_state = Column(String(30), nullable=True)
    attributes = Column(JSON, nullable=True)
    frozen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MapPackageArtifact(Base):
    """地图包物理文件的受控索引。"""

    __tablename__ = "map_package_artifacts"
    __table_args__ = (
        Index("ix_map_artifacts_snapshot_kind", "snapshot_id", "artifact_kind"),
    )

    id = Column(Integer, primary_key=True)
    public_bundle_id = Column(
        Integer,
        ForeignKey("public_map_bundles.id", ondelete="CASCADE"),
        nullable=True,
    )
    snapshot_id = Column(
        String(36),
        ForeignKey("map_snapshots.id", ondelete="CASCADE"),
        nullable=True,
    )
    artifact_kind = Column(String(30), nullable=False)
    storage_key = Column(String(500), nullable=False, unique=True)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
