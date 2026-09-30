"""Read-only case workspace: reference existing outputs, never start analysis."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_pipeline import CasePipelineState
from app.services.case_saved_profile import read_saved_profile
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
        profile = read_saved_profile(db, case)
        try:
            result = CaseResultService.latest(db, case_id)
        except CaseResultAccessError:
            # Missing and revoked references deliberately share one public state.
            result = None
        result_status = ("unavailable" if result is None else
                         "updating" if result.get("freshness") == "pending_update" else "ready")
        from app.config import settings
        from app.services.case_automation_service import CaseAutomationService
        from app.services.case_knowledge_service import CaseKnowledgeService
        from app.services.case_processing_card_service import CaseProcessingCardService
        from app.services.case_profile_service import CaseProfileService

        # Reuse the already-read versions in all compatibility sections. Database
        # failures propagate; no fallback can turn a failed read into empty facts.
        detail = CaseProfileService.build_case_profile(db, case_id, include_similar=False,
                                                       saved_profile=profile)
        result_module = {"status": result_status, "data": result}
        automation = CaseAutomationService.build_automation_workbench(
            db, case, include_bonus=settings.ENABLE_BONUS_ACCOUNTING,
            profile=detail, result_module=result_module,
        )
        processing = CaseProcessingCardService.build_processing_card(
            db, case_id, profile=detail, bonus_assessment=automation.get("bonus_assessment"),
        )
        diagram = CaseKnowledgeService.build_case_diagram(db, case_id, profile=detail)
        return {
            "schema_version": "case-workspace-6.0-1",
            "generated_at": datetime.now(timezone.utc),
            "case_id": case.id,
            "case": {"id": case.id, "case_number": case.case_number,
                     "status": case.status, "operational_area_id": case.operational_area_id},
            "pipeline": {"status": state.status if state else "not_started",
                         "requested_at": state.requested_at if state else None,
                         "completed_at": state.completed_at if state else None},
            "profile": profile,
            "result": result_module,
            "detail_profile": {"status": "ready", "data": detail},
            "processing_card": {"status": "ready", "data": processing},
            "automation_workbench": {"status": "ready", "data": automation},
            "diagram": {"status": "ready", "data": diagram},
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
