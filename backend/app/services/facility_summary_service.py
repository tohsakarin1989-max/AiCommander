"""Small durable catalog projection plus fresh, authorized read-only analysis.

The catalog is reconciled conservatively in bounded batches. Case/profile/road
associations are *not* cached globally: each read recomposes existing derived
evidence under current permissions. This avoids copying cases into an asset
master, stale permission caches, save hooks and a new mandatory user operation.
"""
from datetime import datetime, timezone

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError

from app.models.facility_summary import FacilityDerivedSummary
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import JurisdictionAssetVersion, MapFeatureClaim, MapSource
from app.services.intelligent_query_context import result_hash

VERSION = 'facility-catalog-5.4-1'
PRODUCTION_KEYS = (
    'oil_type', 'owner_unit', 'production_unit', 'production_status', 'facility_category',
    'production_output', 'daily_output', 'production_rate', 'is_high_production',
    'water_cut_min', 'water_cut_max', 'water_cut_unit', 'production_valid_from',
    'production_valid_to', 'region', 'area', 'aliases', 'defense_coverage_status',
)
CHANGE_LABELS = {'identity': '设施身份或位置', 'production': '生产及有效期资料',
                 'history': '设施历史版本', 'sources': '台账来源版本'}


def catalog_content(db, asset):
    """No filenames, source configuration, raw worksheets or case text."""
    history = db.query(JurisdictionAssetVersion).filter_by(asset_id=asset.id).order_by(
        JurisdictionAssetVersion.version).all()
    # Historic claims must still belong to this visible asset and a visible source.
    claims = db.query(MapFeatureClaim, MapSource).join(MapSource, MapSource.id == MapFeatureClaim.source_id).filter(
        MapFeatureClaim.asset_id == asset.id).order_by(MapFeatureClaim.id).all()
    content = {
        'identity': {key: getattr(asset, key) for key in (
            'id', 'operational_area_id', 'external_id', 'canonical_key', 'name', 'asset_type',
            'latitude', 'longitude', 'status', 'verified', 'verification_state', 'valid_from', 'valid_to')},
        'production': {key: (asset.attributes or {}).get(key) for key in PRODUCTION_KEYS},
        'history': [{'version': row.version, 'name': (row.snapshot or {}).get('name'),
                     'source_claim_id': row.source_claim_id, 'change_type': row.change_type,
                     'snapshot_sha256': result_hash(row.snapshot or {})} for row in history],
        'sources': [{'claim_id': claim.id, 'source_id': source.id, 'source_revision': claim.source_revision,
                     'source_record_id': claim.source_record_id, 'raw_hash': claim.raw_hash,
                     'source_status': source.status} for claim, source in claims],
    }
    return jsonable_encoder(content)


def reconcile_catalog(db, *, limit=25):
    """Worker-only entry. Optimistic updates tolerate concurrent bounded workers."""
    if not 1 <= limit <= 100:
        raise ValueError('invalid_facility_batch')
    if db.info.get('principal_user_id') is not None or db.info.get('authorized_area_ids') is not None:
        raise PermissionError('facility_reconcile_requires_service_session')
    rows = db.query(JurisdictionAsset).outerjoin(FacilityDerivedSummary,
        FacilityDerivedSummary.asset_id == JurisdictionAsset.id).order_by(
        func.coalesce(FacilityDerivedSummary.checked_at, datetime(1970, 1, 1)), JurisdictionAsset.id).limit(limit).all()
    updated = unchanged = 0
    for asset in rows:
        content = catalog_content(db, asset)
        digest = result_hash({'version': VERSION, 'content': content})
        existing = db.query(FacilityDerivedSummary).filter_by(asset_id=asset.id).first()
        now = datetime.now(timezone.utc)
        if existing is not None and existing.content_sha256 == digest:
            db.execute(update(FacilityDerivedSummary).where(FacilityDerivedSummary.asset_id == asset.id).values(checked_at=now))
            unchanged += 1
            continue
        changes = [label for key, label in CHANGE_LABELS.items()
                   if existing is None or (existing.payload or {}).get(key) != content[key]]
        if existing is None:
            try:
                with db.begin_nested():
                    db.add(FacilityDerivedSummary(asset_id=asset.id, revision=1,
                        algorithm_version=VERSION, content_sha256=digest, payload=content,
                        changes=changes, updated_at=now, checked_at=now))
                    db.flush()
                updated += 1
            except IntegrityError:
                # Another worker created this rebuildable projection; next sweep
                # reconciles it. Do not retry business mutations.
                continue
        else:
            changed = db.execute(update(FacilityDerivedSummary).where(
                FacilityDerivedSummary.asset_id == asset.id,
                FacilityDerivedSummary.revision == existing.revision).values(
                revision=existing.revision + 1, algorithm_version=VERSION,
                content_sha256=digest, payload=content, changes=changes,
                updated_at=now, checked_at=now)).rowcount
            updated += changed
    db.commit()
    return {'checked': len(rows), 'updated': updated, 'unchanged': unchanged,
            'strategy': 'conservative_catalog_sweep', 'algorithm_version': VERSION}


def summary_metadata(db, asset):
    """The stored payload is never returned, even to a previously authorized user."""
    row = db.query(FacilityDerivedSummary).filter_by(asset_id=asset.id).first()
    base = {'state': 'pending', 'revision': None, 'updated_at': None, 'changes': [],
            'strategy': 'conservative_catalog_sweep_with_live_authorized_analysis',
            'boundary': '后台仅维护生产资料摘要；案件、画像、道路和成果每次按当前权限只读复用，不代表正式确认。'}
    if row is None:
        return base
    current = catalog_content(db, asset)
    # Do not disclose a previous scope's revision/timestamp or names after relocation.
    if (row.payload or {}).get('identity', {}).get('operational_area_id') != asset.operational_area_id:
        return base
    digest = result_hash({'version': VERSION, 'content': current})
    if digest != row.content_sha256:
        return {**base, 'state': 'stale', 'changes': ['资料已变化，后台摘要待更新；下方按当前可见资料读取']}
    return {**base, 'state': 'ready', 'revision': row.revision, 'updated_at': row.updated_at,
            'changes': row.changes}


def read_dossier(db, asset_id, *, start_date=None, end_date=None):
    from app.services.facility_dossier_content import build_dossier_content
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('facility_scope_required')
    asset = db.query(JurisdictionAsset).populate_existing().filter_by(id=asset_id).first()
    if asset is None:
        raise ValueError('facility_not_found')
    content = build_dossier_content(db, asset_id, start_date=start_date, end_date=end_date)
    content['summary'] = summary_metadata(db, asset)
    if content['sections'].get('production', {}).get('state') == 'restricted':
        content['summary'] = {'state': 'restricted', 'revision': None, 'updated_at': None,
                              'changes': [], 'boundary': '来源受限，不返回历史摘要及版本数量'}
    versions = content.setdefault('versions', {})
    versions['section_versions'] = {key: result_hash(value) for key, value in content['sections'].items()}
    versions['view_version'] = result_hash({'content': content, 'user_id': db.info.get('principal_user_id'),
                                          'areas': db.info['authorized_area_ids']})
    return content
