"""Read-only case workspace: reference existing outputs, never start analysis."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile, CasePipelineState
from app.services.case_pipeline_service import (
    CASE_PROFILE_SCHEMA_VERSION, CasePipelineService,
)
from app.services.case_local_semantic_model import resolve_model_plan
from app.services.case_result_access import CaseResultAccessError
from app.services.case_result_service import CaseResultService


class CaseWorkspaceService:
    @staticmethod
    def read(db: Session, case_id: int) -> dict:
        if "authorized_area_ids" not in db.info:
            raise CaseResultAccessError()
        case = db.scalar(select(Case).where(Case.id == case_id)
                         .execution_options(populate_existing=True))
        if case is None:
            raise CaseResultAccessError()
        state = db.scalar(select(CasePipelineState).where(CasePipelineState.case_id == case_id)
                          .execution_options(populate_existing=True))
        profile = db.scalar(select(CaseAnalysisProfile).where(
            CaseAnalysisProfile.case_id == case_id, CaseAnalysisProfile.is_current.is_(True),
        ).order_by(CaseAnalysisProfile.profile_version.desc()).limit(1)
            .execution_options(populate_existing=True))
        current_profile = profile is not None and (
            profile.source_hash == CasePipelineService.source_hash(db, case)
            and profile.schema_version == CASE_PROFILE_SCHEMA_VERSION
            and profile.dictionary_version == resolve_model_plan(db).version
        )
        profile_data = None if profile is None else {
            "id": profile.id, "version": profile.profile_version,
            "schema_version": profile.schema_version,
            "dictionary_version": profile.dictionary_version,
            "source_hash": profile.source_hash, "created_at": profile.created_at,
            "payload": profile.payload,
        }
        try:
            result = CaseResultService.latest(db, case_id)
        except CaseResultAccessError:
            # Missing and revoked references deliberately share one public state.
            result = None
        result_status = ("unavailable" if result is None else
                         "updating" if result.get("freshness") == "pending_update" else "ready")
        return {
            "schema_version": "case-workspace-5.0-1",
            "generated_at": datetime.now(timezone.utc),
            "case_id": case.id,
            "case": {"id": case.id, "case_number": case.case_number,
                     "status": case.status, "operational_area_id": case.operational_area_id},
            "pipeline": {"status": state.status if state else "not_started",
                         "requested_at": state.requested_at if state else None,
                         "completed_at": state.completed_at if state else None},
            "profile": {"status": "ready" if current_profile else
                        "updating" if profile is not None else "unavailable", "data": profile_data},
            "result": {"status": result_status, "data": result},
            "links": {
                "case": f"/cases?caseId={case.id}",
                "analysis": f"/case-intelligence?caseId={case.id}",
                "map": f"/cases/map?caseId={case.id}",
                "evidence": f"/graphs/evidence?caseId={case.id}",
                "report": (f"/reports?resultId={result['id']}" if result else
                           f"/reports?caseId={case.id}"),
            },
            "boundary": "只聚合已录入资料与后台成果，不生成经验卡或报告，不改变案件办理状态。",
        }
