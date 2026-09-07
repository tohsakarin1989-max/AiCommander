"""双域融合研判指定用户只读试用与一键停用 API。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent_runtime.service import AgentRunService
from app.config import settings
from app.database import get_db
from app.services.dual_domain_pilot_service import DualDomainPilotService


router = APIRouter()


class DualDomainControlUpdate(BaseModel):
    enabled: bool
    pilot_user_ids: list[int] = Field(default_factory=list, max_length=50)
    reason: str = Field(..., min_length=2, max_length=500)


class DualDomainSuspendRequest(BaseModel):
    reason: str = Field(..., min_length=2, max_length=500)


def _principal(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None and settings.AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="请先登录")
    return principal


def _principal_user_id(principal) -> int | None:
    return getattr(principal, "user_id", getattr(principal, "id", None))


def _require_access(request: Request, *, admin_only: bool = False):
    if not settings.ENABLE_AGENT_LAB or settings.AGENT_MODE == "off":
        raise HTTPException(status_code=404, detail="双域融合研判未启用")
    principal = _principal(request)
    role = getattr(principal, "role", "admin" if not settings.AUTH_REQUIRED else None)
    if role not in {"admin", "analyst"}:
        raise HTTPException(status_code=403, detail="当前账号无权访问双域融合研判")
    if admin_only and role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可调整试用范围")
    return principal


def _status(db: Session, principal) -> dict[str, Any]:
    return DualDomainPilotService.build_status(
        db,
        principal_user_id=_principal_user_id(principal),
        principal_role=getattr(principal, "role", None),
    )


@router.get("/status")
def get_dual_domain_status(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _require_access(request)
    return _status(db, principal)


@router.put("/control")
def update_dual_domain_control(
    payload: DualDomainControlUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _require_access(request, admin_only=True)
    if payload.enabled and settings.AGENT_MODE != "assist":
        raise HTTPException(status_code=409, detail="双域融合研判试用必须在受控辅助模式开启")
    try:
        DualDomainPilotService.set_control(
            db,
            enabled=payload.enabled,
            pilot_user_ids=payload.pilot_user_ids,
            updated_by=_principal_user_id(principal),
            reason=payload.reason,
        )
    except ValueError as exc:
        messages = {
            "pilot_user_required": "至少选择一名试用用户",
            "pilot_user_not_eligible": "试用用户必须是启用中的管理员或分析员",
            "too_many_pilot_users": "试用用户不能超过50人",
        }
        raise HTTPException(status_code=422, detail=messages.get(str(exc), "试用配置不合法")) from exc
    if not payload.enabled:
        AgentRunService.suspend_dual_domain_pilot(
            db,
            actor_user_id=_principal_user_id(principal),
            reason=payload.reason,
        )
    return _status(db, principal)


@router.post("/suspend")
def suspend_dual_domain(
    payload: DualDomainSuspendRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _require_access(request, admin_only=True)
    current = DualDomainPilotService.get_control(db)
    DualDomainPilotService.set_control(
        db,
        enabled=False,
        pilot_user_ids=current.pilot_user_ids,
        updated_by=_principal_user_id(principal),
        reason=payload.reason,
    )
    AgentRunService.suspend_dual_domain_pilot(
        db,
        actor_user_id=_principal_user_id(principal),
        reason=payload.reason,
    )
    return _status(db, principal)
