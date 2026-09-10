"""v3.4 案件—地图自动融合研判查询与反馈 API。"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.case import Case
from app.models.case_insight import CaseAnalysisRun, CaseHypothesis
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.map_foundation import MapSnapshot
from app.services.case_insight_service import CaseInsightService


router = APIRouter()


class HypothesisFeedbackRequest(BaseModel):
    decision: Literal["useful", "not_useful", "insufficient_information"]
    note: str | None = Field(default=None, max_length=2000)


def _principal(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None and settings.AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="请先登录")
    return principal


def _user_id(principal) -> int | None:
    return getattr(principal, "user_id", getattr(principal, "id", None))


def _case_exists(db: Session, case_id: int) -> None:
    if not db.query(Case.id).filter(Case.id == case_id).first():
        raise HTTPException(status_code=404, detail="案件不存在")


@router.get("/cases/{case_id}/insights/latest")
def latest_case_insights(
    case_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _principal(request)
    _case_exists(db, case_id)
    run = (
        db.query(CaseAnalysisRun)
        .join(CaseAnalysisProfile, CaseAnalysisProfile.id == CaseAnalysisRun.case_profile_id)
        .join(MapSnapshot, MapSnapshot.id == CaseAnalysisRun.map_snapshot_id)
        .filter(CaseAnalysisRun.case_id == case_id)
        .filter(CaseAnalysisProfile.is_current.is_(True), MapSnapshot.status == "current")
        .order_by(CaseAnalysisRun.completed_at.desc(), CaseAnalysisRun.started_at.desc())
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="自动融合研判尚未生成")
    return CaseInsightService.run_to_dict(db, run)


@router.get("/cases/{case_id}/insights/history")
def case_insight_history(
    case_id: int,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _principal(request)
    _case_exists(db, case_id)
    runs = (
        db.query(CaseAnalysisRun)
        .filter(CaseAnalysisRun.case_id == case_id)
        .order_by(CaseAnalysisRun.started_at.desc())
        .limit(limit)
        .all()
    )
    return [CaseInsightService.run_to_dict(db, item) for item in runs]


@router.get("/case-insights/{hypothesis_id}/evidence")
def case_insight_evidence(
    hypothesis_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _principal(request)
    hypothesis = db.query(CaseHypothesis).filter(CaseHypothesis.id == hypothesis_id).first()
    if not hypothesis:
        raise HTTPException(status_code=404, detail="候选推断不存在")
    return {
        "hypothesis_id": hypothesis.id,
        "case_id": hypothesis.case_id,
        "evidence_refs": hypothesis.evidence_refs,
        "supporting_evidence": hypothesis.supporting_evidence,
        "counter_evidence": hypothesis.counter_evidence,
        "information_gaps": hypothesis.information_gaps,
        "score_components": hypothesis.score_components,
        "boundary": hypothesis.boundary,
    }


@router.post("/case-insights/{hypothesis_id}/feedback", status_code=201)
def submit_case_insight_feedback(
    hypothesis_id: str,
    payload: HypothesisFeedbackRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _principal(request)
    role = getattr(principal, "role", "admin" if not settings.AUTH_REQUIRED else None)
    if role not in {"admin", "analyst"}:
        raise HTTPException(status_code=403, detail="只读账号不能提交研判反馈")
    try:
        feedback = CaseInsightService.record_feedback(
            db,
            hypothesis_id=hypothesis_id,
            decision=payload.decision,
            note=payload.note,
            created_by=_user_id(principal),
        )
    except ValueError as exc:
        status = 404 if str(exc) == "hypothesis_not_found" else 422
        raise HTTPException(status_code=status, detail="候选推断不存在" if status == 404 else "反馈选项无效") from exc
    return {
        "id": feedback.id,
        "hypothesis_id": feedback.hypothesis_id,
        "decision": feedback.decision,
        "note": feedback.note,
        "created_at": feedback.created_at,
        "formal_case_changed": False,
    }
