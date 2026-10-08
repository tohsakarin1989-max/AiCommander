"""v3.3 案件自动治理画像查询与管理员回填 API。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile, CasePipelineState
from app.services.case_pipeline_service import CasePipelineService


router = APIRouter()


def _principal(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None and settings.AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="请先登录")
    return principal


def _require_admin(request: Request):
    principal = _principal(request)
    role = getattr(principal, "role", "admin" if not settings.AUTH_REQUIRED else None)
    if role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以启动历史案件画像回填")
    return principal


def _case_exists(db: Session, case_id: int) -> None:
    if not db.query(Case.id).filter(Case.id == case_id).first():
        raise HTTPException(status_code=404, detail="案件不存在")


@router.get("/cases/{case_id}/analysis-profile/latest")
def latest_case_analysis_profile(
    case_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _principal(request)
    _case_exists(db, case_id)
    from app.services.case_saved_profile import read_saved_profile
    case = db.query(Case).filter(Case.id == case_id).first()
    saved = read_saved_profile(db, case)
    if saved["data"] is None:
        raise HTTPException(status_code=404, detail="案件标准画像尚未生成")
    profile = db.query(CaseAnalysisProfile).filter(CaseAnalysisProfile.id == saved["data"]["id"]).first()
    current = saved["status"] == "ready"
    return {**CasePipelineService.profile_to_dict(profile), "is_current": current,
            "freshness": "current" if current else "updating",
            "source_revision_id": profile.source_revision_id,
            "freshness_boundary": "源案件或规则已变化时，此处仅为上一版本；读取不触发重算。"}


@router.get("/cases/{case_id}/pipeline-status")
def case_pipeline_status(
    case_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _principal(request)
    _case_exists(db, case_id)
    state = db.query(CasePipelineState).filter(CasePipelineState.case_id == case_id).first()
    return CasePipelineService.state_to_dict(state, case_id)


@router.post("/admin/case-profiles/backfill")
def backfill_case_profiles(
    request: Request,
    limit: int = Query(default=200, ge=1, le=5000),
    after_id: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(request)
    return CasePipelineService.backfill(db, limit=limit, after_id=after_id)
