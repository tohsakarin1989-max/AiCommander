"""地图数据管家指定用户试用与一键停用 API。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent_runtime.service import AgentRunService
from app.config import settings
from app.database import get_db
from app.services.map_steward_service import MapStewardPilotService


router = APIRouter()


class MapStewardControlUpdate(BaseModel):
    enabled: bool
    mutations_suspended: bool = True
    pilot_user_ids: list[int] = Field(default_factory=list, max_length=50)
    reason: str = Field(..., min_length=2, max_length=500)


class MapStewardSuspendRequest(BaseModel):
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
        raise HTTPException(status_code=404, detail="地图数据管家未启用")
    principal = _principal(request)
    role = getattr(principal, "role", "admin" if not settings.AUTH_REQUIRED else None)
    if role not in {"admin", "analyst"}:
        raise HTTPException(status_code=403, detail="当前账号无权访问地图数据管家")
    if admin_only and role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可调整试用范围")
    return principal


def _status(db: Session, principal) -> dict[str, Any]:
    return MapStewardPilotService.build_status(
        db,
        principal_user_id=_principal_user_id(principal),
        principal_role=getattr(principal, "role", None),
    )


@router.get("/status")
def get_map_steward_status(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _require_access(request)
    return _status(db, principal)


@router.put("/control")
def update_map_steward_control(
    payload: MapStewardControlUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _require_access(request, admin_only=True)
    if payload.enabled and settings.AGENT_MODE != "assist":
        raise HTTPException(status_code=409, detail="地图数据管家试用必须在受控辅助模式开启")
    if not payload.mutations_suspended and not settings.AGENT_MUTATIONS_ENABLED:
        raise HTTPException(status_code=409, detail="全局写入保护仍处于关闭状态")
    try:
        MapStewardPilotService.set_control(
            db,
            enabled=payload.enabled,
            mutations_suspended=payload.mutations_suspended,
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
    if not payload.enabled or payload.mutations_suspended:
        AgentRunService.suspend_map_pilot(
            db,
            actor_user_id=_principal_user_id(principal),
            reason=payload.reason,
        )
    return _status(db, principal)


@router.post("/suspend")
def suspend_map_steward(
    payload: MapStewardSuspendRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _require_access(request, admin_only=True)
    current = MapStewardPilotService.get_control(db)
    MapStewardPilotService.set_control(
        db,
        enabled=False,
        mutations_suspended=True,
        pilot_user_ids=current.pilot_user_ids,
        updated_by=_principal_user_id(principal),
        reason=payload.reason,
    )
    AgentRunService.suspend_map_pilot(
        db,
        actor_user_id=_principal_user_id(principal),
        reason=payload.reason,
    )
    return _status(db, principal)
