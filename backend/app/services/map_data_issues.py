"""Source-bound employee observations; never edits a facility or its claims."""
from __future__ import annotations

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
    issue = JurisdictionFeedback(
        asset_id=asset.id, operational_area_id=asset.operational_area_id,
        feedback_type="data_issue", adopted=False, notes=notes,
        extra={"schema_version": "map-data-issue-7.2-1", "source_reference": reference,
               "actor_id": db.info.get("principal_user_id"), "state": "reported",
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
        except (LookupError, ValueError):
            continue
        visible.append(row)
    offset = (page - 1) * page_size
    return {"items": [{"id": row.id, "asset_id": row.asset_id, "notes": row.notes,
                        "source_reference": row.extra["source_reference"], "state": "reported",
                        "created_at": utc_datetime(row.created_at)}
                       for row in visible[offset:offset + page_size]],
            "total": len(visible), "page": page, "page_size": page_size,
            "boundary": "只表示有人标注了资料问题，不认定设施信息有误，不自动改写生产台账"}
