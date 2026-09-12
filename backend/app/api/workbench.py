"""v2.8 今日研判工作台 API。"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services.daily_workbench_service import DailyWorkbenchService
from app.services.workbench_service import WorkbenchError, WorkbenchService


router = APIRouter()


class WorkbenchSessionCreate(BaseModel):
    task_type: Literal[
        "data_review",
        "experience_generate",
        "experience_review",
        "report_generate",
        "report_review",
    ]
    source_type: Literal["case"]
    source_id: int = Field(..., ge=1)
    entry_path: str = Field(..., min_length=1, max_length=500)


class WorkbenchSessionEvent(BaseModel):
    event: Literal["page_view", "completed", "abandoned"]
    path: Optional[str] = Field(default=None, max_length=500)


def _principal(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None and settings.AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="请先登录")
    return principal


def _identity(request: Request) -> tuple[object, str, Optional[int]]:
    principal = _principal(request)
    role = getattr(principal, "role", "admin" if not settings.AUTH_REQUIRED else None)
    user_id = getattr(principal, "user_id", getattr(principal, "id", None))
    return principal, role, user_id


def _require_editor(request: Request) -> tuple[object, str, Optional[int]]:
    identity = _identity(request)
    if identity[1] not in {"admin", "analyst"}:
        raise HTTPException(status_code=403, detail="只读账号不能记录工作会话")
    return identity


def _raise_workbench_error(exc: WorkbenchError) -> None:
    if str(exc) == "session_not_found":
        raise HTTPException(status_code=404, detail="工作会话不存在")
    if str(exc) == "task_source_not_found":
        raise HTTPException(status_code=404, detail="工作台任务来源不存在")
    if str(exc) == "stale_workbench_task":
        raise HTTPException(status_code=409, detail="任务状态已变化，请刷新工作台后重试")
    if str(exc) == "active_session_conflict":
        raise HTTPException(status_code=409, detail="已有活动任务，请刷新后继续")
    if str(exc) == "invalid_internal_path":
        raise HTTPException(status_code=422, detail="只能记录系统内部页面，且不会保存查询参数")
    raise HTTPException(status_code=422, detail="工作会话操作不合法")


@router.get("/daily")
def get_daily_workbench(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """全量授权统计；缺项与分析状态可重叠，分析就绪不代表案件办结。"""
    _identity(request)
    return DailyWorkbenchService.daily(db, limit=limit, offset=offset)


@router.get("/today")
def get_today_workbench(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    _, role, user_id = _identity(request)
    return WorkbenchService.today(db, role=role, user_id=user_id, limit=limit)


@router.post("/sessions")
def start_workbench_session(
    payload: WorkbenchSessionCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _, _, user_id = _require_editor(request)
    try:
        session, created = WorkbenchService.start_session(
            db,
            user_id=user_id,
            task_type=payload.task_type,
            source_type=payload.source_type,
            source_id=payload.source_id,
            entry_path=payload.entry_path,
        )
    except WorkbenchError as exc:
        _raise_workbench_error(exc)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return {"created": created, "session": WorkbenchService.session_payload(session)}


@router.get("/sessions/active")
def get_active_workbench_session(
    request: Request,
    db: Session = Depends(get_db),
):
    _, _, user_id = _require_editor(request)
    return WorkbenchService.active_session(db, user_id=user_id)


@router.post("/sessions/{session_id}/events")
def record_workbench_event(
    session_id: str,
    payload: WorkbenchSessionEvent,
    request: Request,
    db: Session = Depends(get_db),
):
    _, _, user_id = _require_editor(request)
    try:
        session = WorkbenchService.record_event(
            db,
            session_id=session_id,
            user_id=user_id,
            event=payload.event,
            path=payload.path,
        )
        return WorkbenchService.session_payload(session)
    except WorkbenchError as exc:
        _raise_workbench_error(exc)


@router.get("/metrics")
def get_workbench_metrics(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    _, role, user_id = _require_editor(request)
    return WorkbenchService.metrics(db, role=role, user_id=user_id, days=days)
