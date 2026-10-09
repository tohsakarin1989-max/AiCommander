"""Source-bound employee observations; never edits a facility or its claims."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import require_area_write_access
from app.models.jurisdiction import JurisdictionAsset, JurisdictionFeedback
from app.models.map_foundation import JurisdictionAssetVersion, MapFeatureClaim, MapSource
from app.utils.datetimes import utc_datetime
from app.services.facility_source_access import attributes_sources_visible


FIELD_GROUPS = {"identity", "coordinates", "water_cut", "production", "other"}


def _asset(db: Session, asset_id: int) -> JurisdictionAsset:
    asset = db.query(JurisdictionAsset).populate_existing().filter_by(id=asset_id).first()
    if asset is None:
        raise LookupError("data_issue_reference_unavailable")
    return asset


def validate_reference(db: Session, asset: JurisdictionAsset, reference: dict) -> dict:
    group = reference.get("field_group")
    if group not in FIELD_GROUPS:
        raise ValueError("data_issue_invalid_reference")
    claim_id, version_id = reference.get("source_claim_id"), reference.get("asset_version_id")
    if not any(type(value) is int and value > 0 for value in (claim_id, version_id)):
        raise ValueError("data_issue_reference_required")
    for value in (claim_id, version_id):
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError("data_issue_invalid_reference")
    if claim_id is not None:
        claim = db.query(MapFeatureClaim).join(MapSource, MapSource.id == MapFeatureClaim.source_id).filter(
            MapFeatureClaim.id == claim_id, MapFeatureClaim.asset_id == asset.id,
            MapSource.status == "active", MapSource.operational_area_id == asset.operational_area_id,
        ).first()
        if claim is None:
            raise LookupError("data_issue_reference_unavailable")
        normalized = claim.normalized_payload or {}
        if not isinstance(normalized, dict) or not attributes_sources_visible(
            db, normalized.get("attributes") or {}, asset.operational_area_id,
        ):
            raise LookupError("data_issue_reference_unavailable")
    if version_id is not None:
        version = db.query(JurisdictionAssetVersion).filter_by(id=version_id, asset_id=asset.id).first()
        if version is None:
            raise LookupError("data_issue_reference_unavailable")
        if claim_id is not None and version.source_claim_id != claim_id:
            raise ValueError("data_issue_invalid_reference")
        allowed = db.info.get("authorized_area_ids")
        prior_area = (version.snapshot or {}).get("operational_area_id")
        if allowed is not None and prior_area is not None and prior_area not in allowed:
            raise LookupError("data_issue_reference_unavailable")
        if not attributes_sources_visible(db, (version.snapshot or {}).get("attributes") or {}, asset.operational_area_id):
            raise LookupError("data_issue_reference_unavailable")
        if version.source_claim_id is not None and not db.query(MapFeatureClaim.id).join(
            MapSource, MapSource.id == MapFeatureClaim.source_id,
        ).filter(MapFeatureClaim.id == version.source_claim_id, MapFeatureClaim.asset_id == asset.id,
                 MapSource.status == "active", MapSource.operational_area_id == asset.operational_area_id).first():
            raise LookupError("data_issue_reference_unavailable")
    return {"field_group": group, "source_claim_id": claim_id, "asset_version_id": version_id}


def record_issue(db: Session, data: dict) -> JurisdictionFeedback:
    if type(data.get("asset_id")) is not int or data.get("case_id") is not None:
        raise ValueError("data_issue_asset_required")
    asset = _asset(db, data["asset_id"])
    require_area_write_access(db, asset.operational_area_id)
    notes = str(data.get("notes") or "").strip()
    if not notes or len(notes) > 2000:
        raise ValueError("data_issue_note_required")
    reference = validate_reference(db, asset, data.get("source_reference") or {})
    baseline = db.query(JurisdictionAssetVersion.version).filter_by(asset_id=asset.id).order_by(
        JurisdictionAssetVersion.version.desc()).first()
    issue = JurisdictionFeedback(
        asset_id=asset.id, operational_area_id=asset.operational_area_id,
        feedback_type="data_issue", adopted=False, notes=notes,
        extra={"schema_version": "map-data-issue-7.2-1", "source_reference": reference,
               "actor_id": db.info.get("principal_user_id"), "state": "reported",
               "baseline_asset_version": baseline[0] if baseline else 0,
               "boundary": "这是一条资料问题标注，不是已核实事实，也未修改设施正式字段"},
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return issue


def list_issues(db: Session, asset_id: int, *, page: int, page_size: int) -> dict:
    asset = _asset(db, asset_id)
    query = db.query(JurisdictionFeedback).filter_by(
        asset_id=asset_id, operational_area_id=asset.operational_area_id, feedback_type="data_issue",
    )
    # Validate current access to every referenced source before pagination or
    # counts. Do not leak the text/count of a formerly visible source.
    visible = []
    for row in query.order_by(JurisdictionFeedback.id.desc()):
        reference = (row.extra or {}).get("source_reference") or {}
        try:
            validate_reference(db, asset, reference)
            for resolution in (row.extra or {}).get('resolutions', []):
                if resolution.get('source_reference'):
                    validate_reference(db, asset, resolution['source_reference'])
        except (LookupError, ValueError):
            continue
        visible.append(row)
    offset = (page - 1) * page_size
    return {"items": [_view(row)
                       for row in visible[offset:offset + page_size]],
            "total": len(visible), "page": page, "page_size": page_size,
            "boundary": "只表示有人标注了资料问题，不认定设施信息有误，不自动改写生产台账"}


def _view(row):
    extra = row.extra or {}
    return {'id': row.id, 'asset_id': row.asset_id, 'notes': row.notes,
            'source_reference': extra.get('source_reference'), 'state': extra.get('state', 'reported'),
            'created_at': utc_datetime(row.created_at),
            'resolution': extra.get('resolutions', [])[-1] if extra.get('resolutions') else None}


def list_work(db, *, source_id=None, area_id=None, state=None, page=1, page_size=20):
    query = db.query(JurisdictionFeedback).join(JurisdictionAsset, JurisdictionAsset.id == JurisdictionFeedback.asset_id).filter(
        JurisdictionFeedback.feedback_type == 'data_issue')
    if area_id is not None:
        query = query.filter(JurisdictionAsset.operational_area_id == area_id)
    visible = []
    for row in query.order_by(JurisdictionFeedback.id.desc()):
        asset = _asset(db, row.asset_id)
        reference = (row.extra or {}).get('source_reference') or {}
        try:
            validate_reference(db, asset, reference)
            for resolution in (row.extra or {}).get('resolutions', []):
                if resolution.get('source_reference'):
                    validate_reference(db, asset, resolution['source_reference'])
        except (LookupError, ValueError):
            continue
        if state and (row.extra or {}).get('state', 'reported') != state:
            continue
        if source_id is not None:
            claim_id = reference.get('source_claim_id')
            if not claim_id and reference.get('asset_version_id'):
                version = db.get(JurisdictionAssetVersion, reference['asset_version_id'])
                claim_id = version.source_claim_id if version else None
            claim = db.query(MapFeatureClaim).filter_by(id=claim_id, source_id=source_id).first() if claim_id else None
            if claim is None:
                continue
        visible.append({**_view(row), 'asset_name': asset.name, 'operational_area_id': asset.operational_area_id})
    offset = (page - 1) * page_size
    return {'items': visible[offset:offset + page_size], 'total': len(visible), 'page': page, 'page_size': page_size,
            'boundary': '处理回执说明核对依据；不会代替来源修正，也不会自动改写设施'}


def resolve_issue(db, issue_id, data, *, actor_id):
    query = db.query(JurisdictionFeedback).filter_by(id=issue_id, feedback_type='data_issue')
    if db.bind.dialect.name == 'postgresql':
        query = query.with_for_update()
    row = query.populate_existing().first()
    if row is None:
        raise LookupError('data_issue_reference_unavailable')
    asset = _asset(db, row.asset_id)
    from app.database import require_area_manage_access
    require_area_manage_access(db, asset.operational_area_id)
    extra = deepcopy(row.extra or {})
    validate_reference(db, asset, extra.get('source_reference') or {})
    state = data['state']
    note = data['note'].strip()
    if not note:
        raise ValueError('data_issue_note_required')
    reference = data.get('source_reference')
    if reference:
        reference = validate_reference(db, asset, reference)
    if state == 'corrected':
        old = extra.get('source_reference') or {}
        # Changing the field-group label or adding the version of the same
        # original claim does not constitute a new adopted revision.
        old_versions = db.query(JurisdictionAssetVersion).filter_by(asset_id=asset.id)
        old_versions = old_versions.filter_by(id=old['asset_version_id']) if old.get('asset_version_id') else old_versions.filter_by(source_claim_id=old.get('source_claim_id'))
        old_version = old_versions.order_by(JurisdictionAssetVersion.version.desc()).first()
        new_versions = db.query(JurisdictionAssetVersion).filter_by(asset_id=asset.id)
        if reference and reference.get('asset_version_id'):
            new_versions = new_versions.filter_by(id=reference['asset_version_id'])
        else:
            new_versions = new_versions.filter_by(source_claim_id=(reference or {}).get('source_claim_id'))
        new_version = new_versions.order_by(JurisdictionAssetVersion.version.desc()).first() if reference else None
        if (not reference or reference['field_group'] != old.get('field_group')
                or new_version is None
                or new_version.version <= extra.get('baseline_asset_version', 0)
                or (old_version is not None and new_version.version <= old_version.version)
                or (old.get('source_claim_id') and new_version.source_claim_id == old['source_claim_id'])):
            raise ValueError('data_issue_new_revision_required|确认已修正必须引用该设施同一字段组的新采用版本')
    entries = extra.setdefault('resolutions', [])
    existing = next((item for item in entries if item['request_id'] == data['request_id']), None)
    record = {'request_id': data['request_id'], 'state': state, 'note': note,
              'source_reference': reference, 'actor_id': actor_id}
    if existing:
        if any(existing.get(key) != value for key, value in record.items()):
            raise ValueError('data_issue_request_conflict|此处理凭证已用于不同内容')
        return _view(row)
    if data.get('expected_state') != extra.get('state', 'reported'):
        raise ValueError('data_issue_state_conflict|处理状态已变化，请刷新后再核对')
    if len(entries) >= 100:
        raise ValueError('data_issue_history_limit|该标注处理记录已达上限，请新增有依据的问题标注')
    entries.append({**record, 'resolved_at': datetime.now(timezone.utc).isoformat()})
    extra['state'] = state
    row.extra = extra
    db.commit()
    return _view(row)
