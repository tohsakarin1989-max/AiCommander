"""Version-aware read adapter for the background-produced standard profile."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.case_source import CaseRevision
from app.services.case_local_semantic_model import resolve_model_plan
from app.services.case_pipeline_service import CASE_PROFILE_SCHEMA_VERSION, CasePipelineService
from app.services.case_source_service import CaseSourceService


def read_saved_profile(db: Session, case: Case) -> dict:
    profile = db.scalar(select(CaseAnalysisProfile).where(
        CaseAnalysisProfile.case_id == case.id, CaseAnalysisProfile.is_current.is_(True),
    ).order_by(CaseAnalysisProfile.profile_version.desc()).limit(1)
        .execution_options(populate_existing=True))
    if profile is None:
        return {"status": "unavailable", "data": None}
    semantics = (profile.payload or {}).get("semantics") or {}
    if semantics.get("process") is not None:
        from app.services.case_process_contract import validate_process
        try:
            validate_process(semantics["process"], semantics["source_snapshot"])
            if semantics["process"].get("source_hash") not in (None, profile.source_hash):
                return {"status": "unavailable", "data": None}
            if (semantics["process"]["source_revision_id"] != profile.source_revision_id
                    or profile.payload.get("source_revision_id") != profile.source_revision_id):
                return {"status": "unavailable", "data": None}
            if profile.source_revision_id is not None and db.scalar(select(CaseRevision.id).where(
                    CaseRevision.id == profile.source_revision_id, CaseRevision.case_id == case.id,
                    CaseRevision.source_hash == profile.source_hash)) is None:
                return {"status": "unavailable", "data": None}
        except (ValueError, KeyError, TypeError):
            return {"status": "unavailable", "data": None}
    revision = CaseSourceService.latest_revision(db, case.id)
    current = (profile.source_hash == CasePipelineService.source_hash(db, case)
               and profile.source_revision_id == (revision.id if revision else None)
               and profile.schema_version == CASE_PROFILE_SCHEMA_VERSION
               and profile.dictionary_version == resolve_model_plan(db).version)
    return {"status": "ready" if current else "updating", "data": {
        "id": profile.id, "version": profile.profile_version,
        "schema_version": profile.schema_version, "dictionary_version": profile.dictionary_version,
        "source_hash": profile.source_hash, "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "payload": profile.payload,
    }}
