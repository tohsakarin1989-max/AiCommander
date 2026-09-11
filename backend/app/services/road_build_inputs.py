"""Freeze current internal-road inputs for an authorized graph build.

This produces compiler inputs, not a ready graph. No geometry is connected by
coincidence; the graph compiler must consume verified junctions separately.
"""
from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy import and_, func, select

from app.models.internal_roads import InternalRoadFeatureVersion, InternalRoadImport, InternalRoadReview
from app.models.map_foundation import MapSource
from app.models.road_network import RoadAccessGrant, RoadAccessGroup
from app.models.user import User
from app.services.road_access_policy import InternalRoadConditions, VehicleAssumption, internal_road_eligibility


def freeze_internal_road_inputs(db, *, source_ids: list[int], group_id: int,
                                at: datetime, vehicle: VehicleAssumption):
    if (not isinstance(source_ids, list) or len(source_ids) > 100 or len(set(source_ids)) != len(source_ids)
            or any(type(value) is not int or value <= 0 for value in source_ids)):
        raise ValueError('road_build_sources_invalid')
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError('analysis_timezone_required')
    user_id = db.info.get('principal_user_id')
    if type(user_id) is not int or 'authorized_area_ids' not in db.info:
        raise PermissionError('road_build_not_authorized')
    role = db.execute(select(User.role).where(User.id == user_id, User.is_active.is_(True))).scalar_one_or_none()
    if role != 'admin':
        raise PermissionError('road_build_not_authorized')
    if not source_ids:
        from app.services.road_source_revision import require_empty_internal_road_catalog
        require_empty_internal_road_catalog(db)
    revision = db.execute(select(RoadAccessGroup.policy_revision).where(RoadAccessGroup.id == group_id)).scalar_one_or_none()
    if revision is None:
        raise LookupError('road_group_unavailable')
    sources = db.query(MapSource).populate_existing().filter(MapSource.id.in_(source_ids), MapSource.status == 'active').all()
    scope = db.info['authorized_area_ids']
    if (len(sources) != len(source_ids) or any(source.source_type == 'public_map' or
            (scope is not None and source.operational_area_id not in scope) for source in sources)):
        raise PermissionError('road_build_source_unavailable')
    version = InternalRoadFeatureVersion
    latest = db.query(version.source_id.label('source_id'), version.feature_id.label('feature_id'),
                      func.max(version.import_id).label('import_id')).filter(
                          version.source_id.in_(source_ids)).group_by(version.source_id, version.feature_id).subquery()
    # Include latest entrance/road kind changes; never revive an earlier road row.
    versions = db.query(version).populate_existing().join(latest, and_(version.source_id == latest.c.source_id,
        version.feature_id == latest.c.feature_id, version.import_id == latest.c.import_id)).order_by(
            version.source_id, version.feature_id).limit(10001).all()
    if len(versions) > 10000:
        raise ValueError('road_build_requires_partition')
    batch_ids = {item.import_id for item in versions}
    batches = {item.id: item for item in db.query(InternalRoadImport).populate_existing().filter(InternalRoadImport.id.in_(batch_ids)).all()}
    features = {(batch.id, feature['id']): feature for batch in batches.values() for feature in batch.features}
    reviews = {}
    for review in db.query(InternalRoadReview).populate_existing().filter(InternalRoadReview.import_id.in_(batch_ids)).order_by(
            InternalRoadReview.sequence).all():
        reviews[(review.import_id, review.feature_id)] = review
    grants = {(grant.source_id, grant.feature_id): grant for grant in db.query(RoadAccessGrant).populate_existing().filter(
        RoadAccessGrant.group_id == group_id, RoadAccessGrant.policy_revision == revision,
        RoadAccessGrant.source_id.in_(source_ids)).all()}
    included, excluded, future_changes = [], [], []
    for item in versions:
        feature = features.get((item.import_id, item.feature_id))
        if feature is None:
            raise ValueError('road_build_source_integrity_error')
        if item.kind != 'road':
            continue
        batch = batches[item.import_id]
        review = reviews.get((item.import_id, item.feature_id))
        grant = grants.get((item.source_id, item.feature_id))
        conditions = InternalRoadConditions.model_validate_json(json.dumps(feature['properties'].get('conditions', {})))
        future_changes.extend(value.astimezone(timezone.utc) for value in
                              (conditions.valid_from, conditions.valid_until) if value and value > at)
        eligible = internal_road_eligibility(conditions=conditions, vehicle=vehicle, at=at,
            verified=bool(review and review.decision == 'verified'),
            traversal_permitted=bool(grant and grant.decision == 'allow'))
        entry = {'source_id': item.source_id, 'feature_id': item.feature_id,
                 'import_id': item.import_id, 'input_sha256': batch.input_sha256,
                 'review_id': review.id if review else None, 'grant_id': grant.id if grant else None,
                 'operational_area_id': item.operational_area_id,
                 'conditions': conditions.model_dump(mode='json'), 'reason': eligible.reason,
                 'geometry_evidence': review.connection_evidence if review and review.decision == 'verified' else None}
        if eligible.include:
            included.append({**entry, 'geometry': feature['geometry'], 'direction': eligible.direction})
        else:
            excluded.append(entry)
    result = {'schema_version': 'internal-road-build-inputs-4.2.0-1',
              'group_id': group_id, 'policy_revision': revision,
              'condition_time': at.astimezone(timezone.utc).isoformat(),
              'next_condition_change_at': min(future_changes).isoformat() if future_changes else None,
              'vehicle': vehicle.model_dump(mode='json'), 'source_ids': sorted(source_ids),
              'internal_area_ids': sorted({source.operational_area_id for source in sources}),
              'included': included, 'excluded': excluded,
              'connection_policy': 'explicit_verified_junctions_only', 'graph_ready': False}
    # Return a detached snapshot; callers cannot mutate ORM JSON through it.
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return {**json.loads(encoded), 'manifest_sha256': hashlib.sha256(encoded.encode()).hexdigest()}
