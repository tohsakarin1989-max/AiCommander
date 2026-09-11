"""Administrator correspondence review; geometry agreement requires human evidence.

The builder must additionally verify the public PBF hash and referenced way.
These records are not automatically transferred to another source version.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import require_area_write_access
from app.models.internal_roads import InternalRoadImport
from app.models.road_public_alias import RoadPublicAlias
from app.models.user import User


class AliasDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    import_id: int = Field(gt=0)
    feature_id: str = Field(min_length=1, max_length=100)
    public_source_sha256: str = Field(pattern='^[a-f0-9]{64}$')
    osm_way_id: int = Field(gt=0, le=9007199254740991)
    decision: Literal['verified', 'revoked']
    request_key: str = Field(min_length=1, max_length=80)
    evidence_reference: str = Field(min_length=1, max_length=500)
    previous_id: int | None = Field(default=None, gt=0)

    @field_validator('feature_id', 'request_key', 'evidence_reference')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('alias_evidence_required')
        return value


def record_alias_decision(db, data: AliasDecision):
    actor = db.info.get('principal_user_id')
    if (type(actor) is not int or 'authorized_area_ids' not in db.info
            or 'area_access_levels' not in db.info or db.info['area_access_levels'] is None):
        raise PermissionError('road_alias_not_authorized')
    role = db.execute(select(User.role).where(User.id == actor, User.is_active.is_(True))).scalar_one_or_none()
    if role != 'admin':
        raise PermissionError('road_alias_not_authorized')
    batch = db.query(InternalRoadImport).filter_by(id=data.import_id).with_for_update().first()
    if batch is None:
        raise LookupError('road_alias_source_unavailable')
    require_area_write_access(db, batch.operational_area_id)
    if not any(feature['id'] == data.feature_id and feature['properties']['kind'] == 'road' for feature in batch.features):
        raise ValueError('road_alias_requires_road_feature')
    repeated = db.query(RoadPublicAlias).filter_by(import_id=data.import_id, request_key=data.request_key).first()
    fields = data.model_dump(exclude={'previous_id'})
    if repeated:
        if repeated.created_by != actor or any(getattr(repeated, key) != value for key, value in fields.items()):
            raise ValueError('road_alias_request_conflict')
        return repeated, False
    latest = db.query(RoadPublicAlias).filter_by(import_id=data.import_id, feature_id=data.feature_id,
        public_source_sha256=data.public_source_sha256, osm_way_id=data.osm_way_id).order_by(RoadPublicAlias.sequence.desc()).first()
    if data.previous_id != (latest.id if latest else None):
        raise ValueError('road_alias_review_changed')
    record = RoadPublicAlias(**fields, operational_area_id=batch.operational_area_id,
                            sequence=latest.sequence + 1 if latest else 1, created_by=actor)
    try:
        with db.begin_nested():
            db.add(record)
            db.flush()
    except IntegrityError as error:
        raise ValueError('road_alias_concurrent_review') from error
    return record, True


def current_aliases(db, *, import_id: int, feature_id: str, public_source_sha256: str):
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('road_alias_scope_required')
    rows = db.query(RoadPublicAlias).filter_by(import_id=import_id, feature_id=feature_id,
        public_source_sha256=public_source_sha256).order_by(RoadPublicAlias.sequence).all()
    latest = {row.osm_way_id: row for row in rows}
    return [row for _, row in sorted(latest.items()) if row.decision == 'verified']


def describe_alias(record):
    return {key: getattr(record, key) for key in (
        'id', 'import_id', 'feature_id', 'public_source_sha256', 'osm_way_id',
        'sequence', 'decision', 'request_key', 'evidence_reference', 'created_by')} | {
            'created_at': record.created_at.isoformat(), 'routing_available': False,
            'boundary': '仅记录整段道路对应核验；不是通行许可，构图前仍须核对源文件和路段。'}


def alias_history(db, *, import_id, feature_id, public_source_sha256, limit=20, before_id=None):
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('road_alias_scope_required')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('road_alias_limit_invalid')
    query = db.query(RoadPublicAlias).filter_by(import_id=import_id, feature_id=feature_id,
                                               public_source_sha256=public_source_sha256)
    if before_id is not None:
        query = query.filter(RoadPublicAlias.id < before_id)
    rows = query.order_by(RoadPublicAlias.id.desc()).limit(limit + 1).all()
    return {'items': [describe_alias(row) for row in rows[:limit]],
            'next_before_id': rows[limit - 1].id if len(rows) > limit else None}
