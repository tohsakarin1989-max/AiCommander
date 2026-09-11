"""Live source revision for governed graphs; no cached ORM authorization state.

Import batches are immutable application records, identified by their source
hash. Read current index/review/alias/grant rows on each graph authorization so
changes invalidate a graph before a replacement finishes building.
"""
import hashlib
import json
import re

from sqlalchemy import and_, func, select

from app.models.internal_roads import InternalRoadFeatureVersion, InternalRoadImport, InternalRoadReview
from app.models.map_foundation import MapSource, OperationalArea, PublicMapBundle
from app.models.road_network import RoadAccessGroup, RoadAccessGrant
from app.models.road_public_alias import RoadPublicAlias


def require_empty_internal_road_catalog(db):
    """Public-only bootstrap must not omit known internal restrictions.

    Check the catalog, not the caller's narrowed visibility; return no identities.
    A first internal-road import invalidates the public-only graph on next read.
    """
    # Core existence check deliberately has no ORM area filter: narrowing the
    # caller's scope cannot certify that the server has no internal restrictions.
    # No business rows or identifiers are returned by this server-only guard.
    features = InternalRoadFeatureVersion.__table__
    sources = MapSource.__table__
    known = db.scalar(select(select(features.c.id).select_from(
        features.join(sources, sources.c.id == features.c.source_id)
    ).where(sources.c.status == 'active',
            sources.c.source_type != 'public_map').exists()))
    if known:
        raise ValueError('road_source_revision_catalog_incomplete')


def source_revision(db, *, source_ids, group_id, public_bundle_id, public_source_sha256):
    if (type(db.info.get('principal_user_id')) is not int or 'authorized_area_ids' not in db.info):
        raise PermissionError('road_source_revision_not_authorized')
    if (not isinstance(source_ids, list) or len(source_ids) > 100
            or any(type(value) is not int or value <= 0 for value in source_ids)
            or len(set(source_ids)) != len(source_ids)
            or type(group_id) is not int or group_id <= 0
            or type(public_bundle_id) is not int or public_bundle_id <= 0
            or not isinstance(public_source_sha256, str) or not re.fullmatch('[a-f0-9]{64}', public_source_sha256)):
        raise ValueError('road_source_revision_arguments_invalid')
    if not source_ids:
        require_empty_internal_road_catalog(db)
    sources = db.execute(select(MapSource.id, MapSource.source_type, MapSource.status, MapSource.trust_rank,
        MapSource.operational_area_id, OperationalArea.status.label('area_status'))
        .join(OperationalArea, OperationalArea.id == MapSource.operational_area_id)
        .where(MapSource.id.in_(source_ids)).order_by(MapSource.id)).mappings().all()
    scope = db.info['authorized_area_ids']
    if len(sources) != len(source_ids) or (scope is not None and any(row['operational_area_id'] not in scope for row in sources)):
        raise PermissionError('road_source_revision_not_authorized')
    # Newly registered road sources in an already compiled area must not be
    # silently ignored (they may identify a formerly public way as restricted).
    area_ids = {row['operational_area_id'] for row in sources}
    omitted = db.execute(select(MapSource.id).where(MapSource.operational_area_id.in_(area_ids),
        MapSource.status == 'active', MapSource.source_type != 'public_map', ~MapSource.id.in_(source_ids),
        select(InternalRoadFeatureVersion.id).where(
            InternalRoadFeatureVersion.source_id == MapSource.id).exists()).limit(1)).scalar_one_or_none()
    if omitted is not None:
        raise ValueError('road_source_revision_catalog_incomplete')
    group_revision = db.execute(select(RoadAccessGroup.policy_revision).where(RoadAccessGroup.id == group_id)).scalar_one_or_none()
    if group_revision is None:
        raise ValueError('road_source_revision_group_missing')
    version = InternalRoadFeatureVersion
    latest = select(version.source_id, version.feature_id, func.max(version.import_id).label('import_id')).where(
        version.source_id.in_(source_ids)).group_by(version.source_id, version.feature_id).subquery()
    versions = db.execute(select(version.source_id, version.feature_id, version.import_id,
        version.operational_area_id, version.kind).join(latest, and_(version.source_id == latest.c.source_id,
        version.feature_id == latest.c.feature_id, version.import_id == latest.c.import_id))
        .order_by(version.source_id, version.feature_id).limit(10001)).mappings().all()
    if len(versions) > 10000:
        raise ValueError('road_source_revision_requires_partition')
    batches = {row['import_id'] for row in versions}
    imports = db.execute(select(InternalRoadImport.id, InternalRoadImport.source_id,
        InternalRoadImport.operational_area_id, InternalRoadImport.input_sha256, InternalRoadImport.schema_version)
        .where(InternalRoadImport.id.in_(batches)).order_by(InternalRoadImport.id)).mappings().all()
    reviews = {}
    for row in db.execute(select(InternalRoadReview.id, InternalRoadReview.import_id,
        InternalRoadReview.feature_id, InternalRoadReview.sequence, InternalRoadReview.decision,
        InternalRoadReview.evidence_reference, InternalRoadReview.connection_evidence)
        .where(InternalRoadReview.import_id.in_(batches)).order_by(InternalRoadReview.sequence)).mappings():
        reviews[(row['import_id'], row['feature_id'])] = dict(row)
    aliases = {}
    for row in db.execute(select(RoadPublicAlias.id, RoadPublicAlias.import_id, RoadPublicAlias.feature_id,
        RoadPublicAlias.osm_way_id, RoadPublicAlias.sequence, RoadPublicAlias.decision, RoadPublicAlias.evidence_reference)
        .where(RoadPublicAlias.import_id.in_(batches), RoadPublicAlias.public_source_sha256 == public_source_sha256)
        .order_by(RoadPublicAlias.sequence)).mappings():
        aliases[(row['import_id'], row['feature_id'], row['osm_way_id'])] = dict(row)
    grants = db.execute(select(RoadAccessGrant.id, RoadAccessGrant.source_id, RoadAccessGrant.feature_id,
        RoadAccessGrant.decision, RoadAccessGrant.evidence_reference)
        .where(RoadAccessGrant.group_id == group_id, RoadAccessGrant.policy_revision == group_revision,
               RoadAccessGrant.source_id.in_(source_ids)).order_by(RoadAccessGrant.source_id, RoadAccessGrant.feature_id)).mappings().all()
    bundle = db.execute(select(PublicMapBundle.id, PublicMapBundle.package_hash, PublicMapBundle.status,
        PublicMapBundle.license_record, PublicMapBundle.manifest).where(PublicMapBundle.id == public_bundle_id)).mappings().first()
    if bundle is None:
        raise ValueError('road_source_revision_bundle_missing')
    content = {'sources': [dict(row) for row in sources], 'policy_revision': group_revision,
               'versions': [dict(row) for row in versions], 'imports': [dict(row) for row in imports],
               'reviews': [reviews[key] for key in sorted(reviews)],
               'aliases': [aliases[key] for key in sorted(aliases)],
               'grants': [dict(row) for row in grants], 'public_bundle': dict(bundle)}
    digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                       separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return {'schema_version': 'road-source-revision-4.2.0-1', 'source_ids': sorted(source_ids),
            'internal_area_ids': sorted({row['operational_area_id'] for row in sources}),
            'group_id': group_id, 'public_bundle_id': public_bundle_id,
            'public_source_sha256': public_source_sha256, 'sha256': digest}
