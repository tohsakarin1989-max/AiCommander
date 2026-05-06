"""涉油案件研判工作台 API。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.case_intelligence_service import CaseIntelligenceService


router = APIRouter()


class TagOverrideItem(BaseModel):
    key: str = Field(..., min_length=1)
    label: Optional[str] = None
    category: Optional[str] = "manual"
    confidence: Optional[float] = Field(default=1.0, ge=0, le=1)
    basis: Optional[List[str]] = None


class TagOverrideRequest(BaseModel):
    added: Optional[List[TagOverrideItem]] = None
    removed_keys: Optional[List[str]] = None


def _handle_service_error(exc: ValueError) -> None:
    message = str(exc)
    if message == "case_not_found":
        raise HTTPException(status_code=404, detail="案件不存在")
    if message == "case_id_required":
        raise HTTPException(status_code=400, detail="缺少 case_id")
    raise HTTPException(status_code=400, detail=message)


@router.get("/workbench")
def get_case_intelligence_workbench(
    case_id: Optional[int] = None,
    days: int = 365,
    limit: int = 8,
    radius_km: float = 1.5,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """获取完整案件研判工作台数据。"""
    try:
        return CaseIntelligenceService.build_workbench(
            db,
            case_id=case_id,
            days=days,
            limit=limit,
            radius_km=radius_km,
        )
    except ValueError as exc:
        _handle_service_error(exc)


@router.get("/cases/{case_id:int}/tags")
def get_case_tags(case_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """获取案件确定性特征标签。"""
    try:
        case = CaseIntelligenceService._get_case(db, case_id)
        return CaseIntelligenceService.build_case_tags(db, case)
    except ValueError as exc:
        _handle_service_error(exc)


@router.put("/cases/{case_id:int}/tag-overrides")
def update_case_tag_overrides(
    case_id: int,
    payload: TagOverrideRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """人工增补或屏蔽标签，结果存入 Case.features.intelligence.tag_overrides。"""
    try:
        added = [item.model_dump(exclude_none=True) for item in payload.added or []]
        return CaseIntelligenceService.update_tag_overrides(
            db,
            case_id=case_id,
            added=added,
            removed_keys=payload.removed_keys or [],
        )
    except ValueError as exc:
        _handle_service_error(exc)


@router.get("/cases/{case_id:int}/similar")
def get_similar_cases(
    case_id: int,
    days: int = 365,
    limit: int = 10,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """按作案条件和现场要素查找相似案件。"""
    try:
        return CaseIntelligenceService.find_similar_cases(
            db,
            case_id=case_id,
            days=days,
            limit=limit,
        )
    except ValueError as exc:
        _handle_service_error(exc)


@router.get("/spatiotemporal")
def get_spatiotemporal_patterns(
    days: int = 365,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """获取历史案件时空规律。"""
    return CaseIntelligenceService.analyze_spatiotemporal_patterns(db, days=days)


@router.get("/cases/{case_id:int}/scene")
def get_scene_factors(
    case_id: int,
    days: int = 365,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """获取单案现场条件、车辆工具和抓获经验研判。"""
    try:
        return CaseIntelligenceService.analyze_scene_factors(db, case_id=case_id, days=days)
    except ValueError as exc:
        _handle_service_error(exc)


@router.get("/area-profiles")
def get_area_profiles(
    days: int = 365,
    limit: int = 10,
    radius_km: float = 1.5,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """获取辖区风险区域画像。"""
    return CaseIntelligenceService.build_area_risk_profiles(
        db,
        days=days,
        limit=limit,
        radius_km=radius_km,
    )


@router.get("/prevention-suggestions")
def get_prevention_suggestions(
    case_id: Optional[int] = None,
    days: int = 365,
    limit: int = 8,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """生成防控建议草案，不生成执行任务。"""
    try:
        return CaseIntelligenceService.build_prevention_suggestions(
            db,
            case_id=case_id,
            days=days,
            limit=limit,
        )
    except ValueError as exc:
        _handle_service_error(exc)


@router.get("/cases/{case_id:int}/experience-card")
def get_experience_card(case_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """获取案件复盘经验卡。"""
    try:
        return CaseIntelligenceService.build_experience_card(db, case_id=case_id)
    except ValueError as exc:
        _handle_service_error(exc)


@router.get("/report")
def get_intelligence_report(
    case_id: Optional[int] = None,
    days: int = 365,
    limit: int = 8,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """生成可导出的研判报告结构和 Markdown。"""
    try:
        return CaseIntelligenceService.build_report(
            db,
            case_id=case_id,
            days=days,
            limit=limit,
        )
    except ValueError as exc:
        _handle_service_error(exc)


@router.get("/llm-context")
def get_llm_context_pack(
    case_id: Optional[int] = None,
    days: int = 365,
    limit: int = 8,
    radius_km: float = 1.5,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """生成供大模型读取的事实/推断/建议/缺口上下文包。"""
    try:
        return CaseIntelligenceService.build_llm_context_pack(
            db,
            case_id=case_id,
            days=days,
            limit=limit,
            radius_km=radius_km,
        )
    except ValueError as exc:
        _handle_service_error(exc)
