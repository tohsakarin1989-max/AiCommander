"""v3.5 技防聚合数据、态势简报与部署参考 API。"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.deployment_advisor import (
    DeploymentRecommendation,
    SituationBrief,
)
from app.models.map_foundation import OperationalArea
from app.services.deployment_advisor_service import DeploymentAdvisorService


router = APIRouter()


class TechDefenseImportRequest(BaseModel):
    """只接受聚合摘要；额外字段会被拒绝，避免原图或完整车牌进入系统。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_key: str = Field(min_length=1, max_length=100)
    source_name: str = Field(min_length=1, max_length=200)
    operational_area_id: int | None = Field(default=None, ge=1)
    area_code: str | None = Field(default=None, min_length=1, max_length=100)
    period_start: datetime
    period_end: datetime
    device_type: Literal["camera", "alarm", "lighting", "checkpoint", "other"]
    online_count: int = Field(default=0, ge=0)
    offline_count: int = Field(default=0, ge=0)
    alert_count: int = Field(default=0, ge=0)
    redacted_vehicle_event_count: int = Field(default=0, ge=0)
    disposition_summary: str | None = Field(default=None, max_length=1000)

    @field_validator("disposition_summary")
    @classmethod
    def reject_sensitive_identifiers(cls, value: str | None) -> str | None:
        if not value:
            return value
        patterns = (
            r"(?<!\d)1[3-9]\d{9}(?!\d)",
            r"(?<!\d)\d{17}[\dXx](?!\w)",
            r"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-Z][A-Z0-9]{5,6}",
            r"[+-]?\d{2,3}\.\d{4,}\s*[,，]\s*[+-]?\d{2,3}\.\d{4,}",
        )
        if any(re.search(pattern, value) for pattern in patterns):
            raise ValueError("处置摘要只能包含聚合脱敏内容")
        return value


class RecommendationFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["adopt_reference", "not_adopted", "insufficient_information"]
    usefulness_score: int | None = Field(default=None, ge=1, le=5)
    note: str | None = Field(default=None, max_length=2000)


def _principal(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None and settings.AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="请先登录")
    return principal


def _user_id(principal) -> int | None:
    return getattr(principal, "user_id", getattr(principal, "id", None))


def _require_admin(request: Request):
    principal = _principal(request)
    role = getattr(principal, "role", "admin" if not settings.AUTH_REQUIRED else None)
    if role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以导入技防摘要")
    return principal


def _resolve_area(db: Session, payload: TechDefenseImportRequest) -> OperationalArea:
    query = db.query(OperationalArea).filter(OperationalArea.status == "active")
    if payload.operational_area_id is not None:
        area = query.filter(OperationalArea.id == payload.operational_area_id).first()
    elif payload.area_code:
        area = query.filter(OperationalArea.code == payload.area_code).first()
    else:
        raise HTTPException(status_code=422, detail="必须提供厂区编号或厂区代码")
    if not area:
        raise HTTPException(status_code=404, detail="厂区不存在")
    return area


@router.post("/tech-defense/import-summary", status_code=201)
def import_tech_defense_summary(
    payload: TechDefenseImportRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(request)
    area = _resolve_area(db, payload)
    try:
        aggregate, replay = DeploymentAdvisorService.import_tech_summary(
            db,
            source_key=payload.source_key,
            source_name=payload.source_name,
            operational_area_id=area.id,
            period_start=payload.period_start,
            period_end=payload.period_end,
            device_type=payload.device_type,
            online_count=payload.online_count,
            offline_count=payload.offline_count,
            alert_count=payload.alert_count,
            redacted_vehicle_event_count=payload.redacted_vehicle_event_count,
            disposition_summary=payload.disposition_summary,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="技防摘要时间范围无效") from exc
    return {
        "id": aggregate.id,
        "operational_area_id": aggregate.operational_area_id,
        "period_start": aggregate.period_start,
        "period_end": aggregate.period_end,
        "device_type": aggregate.device_type,
        "replay": replay,
        "raw_media_stored": False,
        "complete_plate_stored": False,
    }


@router.get("/situation/briefs/latest")
def latest_situation_brief(
    request: Request,
    operational_area_id: int | None = Query(default=None, ge=1),
    period_type: Literal["daily", "weekly"] = Query(default="daily"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _principal(request)
    area_id = _read_area_id(db, operational_area_id)
    brief = (
        db.query(SituationBrief)
        .filter(
            SituationBrief.operational_area_id == area_id,
            SituationBrief.period_type == period_type,
        )
        .order_by(SituationBrief.generated_at.desc())
        .first()
    )
    if not brief:
        raise HTTPException(status_code=404, detail="态势简报尚未生成")
    return DeploymentAdvisorService.brief_to_dict(db, brief)


@router.get("/situation/briefs/history")
def situation_brief_history(
    request: Request,
    operational_area_id: int | None = Query(default=None, ge=1),
    period_type: Literal["daily", "weekly"] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _principal(request)
    area_id = _read_area_id(db, operational_area_id)
    query = db.query(SituationBrief).filter(SituationBrief.operational_area_id == area_id)
    if period_type:
        query = query.filter(SituationBrief.period_type == period_type)
    briefs = query.order_by(SituationBrief.generated_at.desc()).limit(limit).all()
    return [DeploymentAdvisorService.brief_to_dict(db, item) for item in briefs]


@router.post("/deployment-recommendations/{recommendation_id}/feedback", status_code=201)
def submit_deployment_feedback(
    recommendation_id: str,
    payload: RecommendationFeedbackRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _principal(request)
    role = getattr(principal, "role", "admin" if not settings.AUTH_REQUIRED else None)
    if role not in {"admin", "analyst"}:
        raise HTTPException(status_code=403, detail="只读账号不能提交部署建议反馈")
    try:
        feedback = DeploymentAdvisorService.record_feedback(
            db,
            recommendation_id=recommendation_id,
            decision=payload.decision,
            usefulness_score=payload.usefulness_score,
            note=payload.note,
            created_by=_user_id(principal),
        )
    except ValueError as exc:
        status = 404 if str(exc) == "recommendation_not_found" else 422
        raise HTTPException(
            status_code=status,
            detail="部署建议不存在" if status == 404 else "反馈内容无效",
        ) from exc
    recommendation = db.query(DeploymentRecommendation).filter(
        DeploymentRecommendation.id == recommendation_id
    ).first()
    return {
        "id": feedback.id,
        "recommendation_id": recommendation_id,
        "decision": feedback.decision,
        "usefulness_score": feedback.usefulness_score,
        "created_at": feedback.created_at,
        "recommendation_status": recommendation.status if recommendation else "candidate",
        "execution_task_created": False,
    }


@router.post("/admin/situation/briefs/generate")
def generate_situation_brief(
    request: Request,
    operational_area_id: int = Query(ge=1),
    period_type: Literal["daily", "weekly"] = Query(default="daily"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(request)
    try:
        brief, replay = DeploymentAdvisorService.generate_brief(
            db,
            operational_area_id=operational_area_id,
            period_type=period_type,
            as_of=datetime.now(timezone.utc),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="厂区不存在") from exc
    result = DeploymentAdvisorService.brief_to_dict(db, brief)
    result["replay"] = replay
    return result


def _read_area_id(db: Session, requested_area_id: int | None) -> int:
    if requested_area_id is not None:
        allowed = db.info.get("authorized_area_ids")
        if allowed is not None and requested_area_id not in allowed:
            raise HTTPException(status_code=404, detail="厂区不存在或无权访问")
        return requested_area_id
    default_id = db.info.get("default_operational_area_id")
    if default_id is not None:
        return int(default_id)
    area = (
        db.query(OperationalArea)
        .filter(OperationalArea.status == "active")
        .order_by(OperationalArea.is_default.desc(), OperationalArea.id)
        .first()
    )
    if not area:
        raise HTTPException(status_code=404, detail="尚未配置厂区")
    return area.id
