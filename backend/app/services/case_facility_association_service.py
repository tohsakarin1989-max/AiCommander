"""Explicit source-bound recording, never promotion of a machine candidate."""
from datetime import datetime, timezone

from app.database import require_area_write_access
from app.models.case import Case
from app.models.case_facility_association import CaseFacilityAssociation
from app.models.case_source import EvidenceObject, SourceReference
from app.models.jurisdiction import JurisdictionAsset
from app.services.case_source_service import CaseSourceService
from app.services.intelligent_query_tasks import _identity
from app.utils.datetimes import utc_datetime

RELATIONS = {"incident_site": "记录中的案发设施", "recovery_site": "记录中的查获设施", "mentioned": "原文明确提及"}


def _reference_matches(reference, revision):
    if reference is None or revision is None:
        return False
    if reference.kind == 'text':
        return reference.source_revision_id == revision.id
    if reference.kind == 'evidence' and reference.evidence_object_id is not None:
        return any(row.get('evidence_object_id') == reference.evidence_object_id
                   for row in (revision.payload or {}).get('evidence', []))
    return False


def _parents(db, case_id, asset_id, *, write=False):
    user = _identity(db)
    query = db.query(Case).populate_existing().filter_by(id=case_id)
    case = (query.with_for_update() if write else query).first()
    asset = db.query(JurisdictionAsset).populate_existing().filter_by(id=asset_id).first()
    if case is None or asset is None:
        raise PermissionError("case_or_facility_unavailable")
    if write:
        if user.role not in {"admin", "analyst"}:
            raise PermissionError("case_write_required")
        require_area_write_access(db, case.operational_area_id)
    return user, case, asset


def record_association(db, *, case_id, asset_id, source_reference_id, source_revision_id, relation_type, note, request_key):
    user, case, asset = _parents(db, case_id, asset_id, write=True)
    if relation_type not in RELATIONS or not note.strip() or not request_key.strip():
        raise ValueError("invalid_facility_relationship")
    existing = db.query(CaseFacilityAssociation).filter_by(case_id=case_id, request_key=request_key).first()
    if existing is not None:
        if any(getattr(existing, key) != value for key, value in {
            "asset_id": asset_id, "source_reference_id": source_reference_id,
            "source_revision_id": source_revision_id, "relation_type": relation_type,
            "note": note.strip(), "created_by": user.id}.items()):
            raise ValueError("association_request_conflict")
        return existing, False
    latest = CaseSourceService.latest_revision(db, case_id)
    if latest is None or latest.id != source_revision_id:
        raise ValueError("association_source_changed")
    reference = db.query(SourceReference).filter_by(id=source_reference_id, case_id=case_id).first()
    if not _reference_matches(reference, latest):
        raise ValueError("association_reference_unavailable")
    if reference.evidence_object_id is not None:
        obj = db.query(EvidenceObject).filter_by(id=reference.evidence_object_id).first()
        if obj is None or obj.availability != "available":
            raise ValueError("association_reference_unavailable")
    row = CaseFacilityAssociation(case_id=case_id, asset_id=asset_id,
        source_reference_id=source_reference_id, source_revision_id=source_revision_id,
        relation_type=relation_type, note=note.strip(), request_key=request_key,
        created_by=user.id)
    db.add(row)
    db.flush()
    return row, True


def revoke_association(db, identifier, *, note):
    _identity(db)
    row = db.query(CaseFacilityAssociation).filter_by(id=identifier).first()
    if row is None:
        raise PermissionError("association_unavailable")
    user, _, _ = _parents(db, row.case_id, row.asset_id, write=True)
    # Match deletion's Case -> child lock order, then reload under the lock.
    row = db.query(CaseFacilityAssociation).populate_existing().filter_by(id=identifier).with_for_update().first()
    if row is None:
        raise PermissionError("association_unavailable")
    if not note.strip():
        raise ValueError("revoke_reason_required")
    if row.revoked_at is None:
        row.revoked_at, row.revoked_by, row.revoke_note = datetime.now(timezone.utc), user.id, note.strip()
        db.flush()
    return row


def view_association(db, row):
    # Callers must first establish current scope and select the visible parent.
    case = db.query(Case).populate_existing().filter_by(id=row.case_id).first()
    asset = db.query(JurisdictionAsset).populate_existing().filter_by(id=row.asset_id).first()
    reference = db.query(SourceReference).filter_by(id=row.source_reference_id, case_id=row.case_id).first()
    if case is None or asset is None or reference is None:
        raise PermissionError("association_source_unavailable")
    latest = CaseSourceService.latest_revision(db, case.id)
    evidence_state = "available"
    if reference.evidence_object_id is not None:
        obj = db.query(EvidenceObject).filter_by(id=reference.evidence_object_id).first()
        evidence_state = obj.availability if obj is not None else "unavailable"
    return {"id": row.id, "case_id": case.id, "asset_id": asset.id,
        "case_number": case.case_number, "asset_name": asset.name,
        "source_reference_id": row.source_reference_id, "source_revision_id": row.source_revision_id,
        "relation_type": row.relation_type, "label": RELATIONS.get(row.relation_type, "人工记录关联"),
        "note": row.note, "status": "revoked" if row.revoked_at else "recorded",
        "source_state": "current" if latest and latest.id == row.source_revision_id and _reference_matches(reference, latest) else "stale",
        "evidence_state": evidence_state,
        "created_at": utc_datetime(row.created_at), "revoked_at": utc_datetime(row.revoked_at),
        "evidence_refs": [f"case_revision:{row.source_revision_id}", f"source_reference:{row.source_reference_id}", f"asset:{asset.id}"],
        "boundary": "人工记录所引材料中的关系，不因登记而证明实际盗取来源；不用于自动确认串并案。"}
