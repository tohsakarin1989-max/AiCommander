"""Road passage authorization is separate from operational-area data visibility."""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class RoadAccessGroup(Base):
    __tablename__ = 'road_access_groups'
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True)
    policy_revision = Column(Integer, nullable=False, default=1)
    __table_args__ = (CheckConstraint('policy_revision > 0', name='ck_road_group_revision'),)


class RoadAccessMembership(Base):
    __tablename__ = 'road_access_memberships'
    group_id = Column(Integer, ForeignKey('road_access_groups.id', ondelete='RESTRICT'), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='RESTRICT'), primary_key=True)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (CheckConstraint('valid_until IS NULL OR valid_until > valid_from', name='ck_road_membership_interval'),)


class RoadAccessGrant(Base):
    """Append-only policy-version entries; no grant is inferred from a map role."""
    __tablename__ = 'road_access_grants'
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey('road_access_groups.id', ondelete='RESTRICT'), nullable=False, index=True)
    policy_revision = Column(Integer, nullable=False)
    source_id = Column(Integer, ForeignKey('map_sources.id', ondelete='RESTRICT'), nullable=False)
    feature_id = Column(String(100), nullable=False)
    decision = Column(String(10), nullable=False)
    evidence_reference = Column(String(500), nullable=False)
    created_by = Column(Integer, ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint('group_id', 'policy_revision', 'source_id', 'feature_id', name='uq_road_grant_version'),
        CheckConstraint("decision IN ('allow', 'deny')", name='ck_road_grant_decision'),
        CheckConstraint('policy_revision > 0', name='ck_road_grant_revision'),
    )


class RoadNetworkVersion(Base):
    """A graph is bound to exact inputs and policy; readiness is not reachability."""
    __tablename__ = 'road_network_versions'
    id = Column(String(36), primary_key=True)
    group_id = Column(Integer, ForeignKey('road_access_groups.id', ondelete='RESTRICT'), nullable=False, index=True)
    policy_revision = Column(Integer, nullable=False)
    public_bundle_id = Column(Integer, ForeignKey('public_map_bundles.id', ondelete='RESTRICT'), nullable=False)
    input_sha256 = Column(String(64), nullable=False)
    conditions_sha256 = Column(String(64), nullable=False)
    source_manifest = Column(JSON, nullable=False)
    engine_version = Column(String(80), nullable=False)
    builder_version = Column(String(80), nullable=False)
    status = Column(String(20), nullable=False, default='building')
    graph_sha256 = Column(String(64), nullable=True)
    artifact_key = Column(String(200), nullable=True)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint('group_id', 'policy_revision', 'input_sha256', 'conditions_sha256',
                         'engine_version', 'builder_version', name='uq_road_network_inputs'),
        CheckConstraint("status IN ('building', 'ready', 'failed', 'retired')", name='ck_road_network_status'),
        CheckConstraint("status != 'ready' OR (graph_sha256 IS NOT NULL AND artifact_key IS NOT NULL)", name='ck_road_network_ready'),
        CheckConstraint('valid_until IS NULL OR valid_until > valid_from', name='ck_road_network_interval'),
        CheckConstraint('policy_revision > 0', name='ck_road_network_revision'),
    )
