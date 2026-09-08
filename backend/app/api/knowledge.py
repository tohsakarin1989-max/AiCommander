from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services.case_knowledge_service import CaseKnowledgeService
from app.services.knowledge_asset_service import KnowledgeAssetError, KnowledgeAssetService


router = APIRouter()


class ExperienceCardStatusRequest(BaseModel):
    status: str
    reviewer: Optional[str] = None
    note: Optional[str] = None


class KnowledgeAssetReviewRequest(BaseModel):
    status: Literal["confirmed", "archived"]
    note: Optional[str] = Field(default=None, max_length=1000)


class ReportSnapshotRequest(BaseModel):
    experience_asset_ids: list[int] = Field(default_factory=list, max_length=10)
    days: int = Field(default=365, ge=1, le=3650)
    limit: int = Field(default=8, ge=1, le=20)


class ReuseDecisionRequest(BaseModel):
    source_asset_id: int
    target_case_id: int
    decision: Literal["accepted", "rejected"]
    purpose: str = Field(..., min_length=1, max_length=200)
    note: Optional[str] = Field(default=None, max_length=1000)


def _principal(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None and settings.AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="请先登录")
    return principal


def _require_editor(request: Request):
    principal = _principal(request)
    role = getattr(principal, "role", "admin" if not settings.AUTH_REQUIRED else None)
    if role not in {"admin", "analyst"}:
        raise HTTPException(status_code=403, detail="当前账号无权生成或审核知识资产")
    return principal


def _principal_user_id(principal) -> Optional[int]:
    return getattr(principal, "user_id", getattr(principal, "id", None))


def _reviewer_label(principal) -> str:
    return (
        getattr(principal, "display_name", None)
        or getattr(principal, "username", None)
        or "人工复核"
    )


def _raise_asset_error(exc: KnowledgeAssetError) -> None:
    code = str(exc)
    if code == "case_not_found":
        raise HTTPException(status_code=404, detail="案件不存在")
    if code == "knowledge_asset_not_found" or code == "experience_asset_not_found":
        raise HTTPException(status_code=404, detail="知识资产不存在")
    if code == "source_changed_since_generation":
        raise HTTPException(status_code=409, detail="源案件已变化，请重新生成后复核")
    if code == "experience_asset_not_reusable":
        raise HTTPException(status_code=422, detail="只能引用已确认且未归档的经验资产")
    if code == "cannot_reuse_same_case":
        raise HTTPException(status_code=422, detail="不能把本案经验卡作为本案历史经验引用")
    if code == "asset_missing_evidence":
        raise HTTPException(status_code=422, detail="知识资产缺少证据引用，不能确认")
    if code == "too_many_experience_assets":
        raise HTTPException(status_code=422, detail="单份报告最多引用10张经验卡")
    if code in {
        "invalid_asset_status",
        "invalid_asset_type",
        "invalid_asset_transition",
        "invalid_reuse_decision",
        "invalid_reuse_purpose",
    }:
        raise HTTPException(status_code=422, detail="知识资产状态或操作不合法")
    raise HTTPException(status_code=400, detail="知识资产操作失败")


@router.get("/experience-cards")
def list_experience_cards(
    status: str = "confirmed",
    limit: int = 50,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return CaseKnowledgeService.list_experience_cards(db, status=status, limit=limit)


@router.get("/experience-cards/search")
def search_experience_cards(
    q: str,
    status: str = "confirmed",
    limit: int = 20,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return CaseKnowledgeService.search_experience_cards(db, q, status=status, limit=limit)


@router.get("/assets")
def list_knowledge_assets(
    asset_type: Optional[str] = None,
    case_id: Optional[int] = None,
    status_value: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """读取独立版本化知识资产；只读用户也可查看。"""
    try:
        return KnowledgeAssetService.list_assets(
            db,
            asset_type=asset_type,
            case_id=case_id,
            status=status_value,
            limit=limit,
        )
    except KnowledgeAssetError as exc:
        _raise_asset_error(exc)


@router.post(
    "/cases/{case_id:int}/experience-assets",
    status_code=status.HTTP_201_CREATED,
)
def generate_experience_asset(
    case_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """从当前案件事实生成经验卡版本；同一来源签名幂等。"""
    principal = _require_editor(request)
    try:
        asset = KnowledgeAssetService.generate_experience_asset(
            db,
            case_id,
            generated_by=_principal_user_id(principal),
        )
        return KnowledgeAssetService.asset_payload(db, asset)
    except KnowledgeAssetError as exc:
        _raise_asset_error(exc)


@router.post(
    "/cases/{case_id:int}/report-snapshots",
    status_code=status.HTTP_201_CREATED,
)
def generate_report_snapshot(
    case_id: int,
    payload: ReportSnapshotRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """生成可复核报告快照，只引用人工选择的已确认经验卡。"""
    principal = _require_editor(request)
    try:
        asset = KnowledgeAssetService.generate_report_snapshot(
            db,
            case_id,
            experience_asset_ids=payload.experience_asset_ids,
            days=payload.days,
            limit=payload.limit,
            generated_by=_principal_user_id(principal),
        )
        return KnowledgeAssetService.asset_payload(db, asset)
    except KnowledgeAssetError as exc:
        _raise_asset_error(exc)


@router.post("/assets/{asset_id:int}/review")
def review_knowledge_asset(
    asset_id: int,
    payload: KnowledgeAssetReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """人工确认或归档固定版本；源案件变化时拒绝确认旧版本。"""
    principal = _require_editor(request)
    try:
        asset = KnowledgeAssetService.review_asset(
            db,
            asset_id,
            status=payload.status,
            reviewed_by=_principal_user_id(principal),
            reviewer_label=_reviewer_label(principal),
            note=payload.note,
        )
        return KnowledgeAssetService.asset_payload(db, asset)
    except KnowledgeAssetError as exc:
        _raise_asset_error(exc)


@router.get("/cases/{case_id:int}/reuse-recommendations")
def get_reuse_recommendations(
    case_id: int,
    days: int = Query(default=730, ge=1, le=3650),
    limit: int = Query(default=8, ge=1, le=20),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """按现场条件推荐已确认历史经验，不自动应用。"""
    try:
        return KnowledgeAssetService.reuse_recommendations(
            db, case_id, days=days, limit=limit
        )
    except KnowledgeAssetError as exc:
        _raise_asset_error(exc)


@router.post("/reuse-decisions")
def record_reuse_decision(
    payload: ReuseDecisionRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """记录经验适用/不适用判断，不修改目标案件。"""
    principal = _require_editor(request)
    try:
        record, created = KnowledgeAssetService.record_reuse_decision(
            db,
            source_asset_id=payload.source_asset_id,
            target_case_id=payload.target_case_id,
            decision=payload.decision,
            purpose=payload.purpose,
            note=payload.note,
            created_by=_principal_user_id(principal),
        )
        response.status_code = (
            status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )
        return KnowledgeAssetService.reuse_payload(db, record)
    except KnowledgeAssetError as exc:
        _raise_asset_error(exc)


@router.get("/reuse-records")
def list_reuse_records(
    target_case_id: int,
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return KnowledgeAssetService.list_reuse_records(
            db, target_case_id=target_case_id, limit=limit
        )
    except KnowledgeAssetError as exc:
        _raise_asset_error(exc)


@router.post("/experience-cards/{case_id:int}/status")
def update_experience_card_status(
    case_id: int,
    payload: ExperienceCardStatusRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _require_editor(request)
    try:
        return CaseKnowledgeService.update_experience_card_status(
            db,
            case_id,
            status=payload.status,
            reviewer=payload.reviewer,
            note=payload.note,
        )
    except ValueError as exc:
        message = str(exc)
        if message == "case_not_found":
            raise HTTPException(status_code=404, detail="案件不存在")
        if message == "experience_card_not_found":
            raise HTTPException(status_code=404, detail="经验卡不存在")
        if message == "invalid_experience_status":
            raise HTTPException(status_code=422, detail="经验卡状态必须为 draft/confirmed/archived")
        raise HTTPException(status_code=400, detail=message)


@router.get("/search")
def search_knowledge(
    q: str,
    case_id: Optional[int] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return CaseKnowledgeService.search(db, q, case_id=case_id, limit=limit)
