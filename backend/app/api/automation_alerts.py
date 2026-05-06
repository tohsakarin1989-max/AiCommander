"""数智自动化告警 API。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.automation_alert_service import AutomationAlertService


router = APIRouter()


class AutomationAlertCreate(BaseModel):
    source_system: Optional[str] = None
    alert_type: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    level: Optional[str] = "medium"
    risk_level: Optional[str] = "high"
    occurred_time: Optional[datetime] = None
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    facility_id: Optional[str] = None
    facility_name: Optional[str] = None
    parameter_snapshot: Optional[Dict[str, Any]] = None
    sensing_summary: Optional[Dict[str, Any]] = None
    ai_assessment: Optional[Dict[str, Any]] = None
    suggested_actions: Optional[List[str]] = None
    is_simulated: Optional[bool] = False


class FalseAlarmRequest(BaseModel):
    note: Optional[str] = None


class AutomationAlertResponse(BaseModel):
    id: int
    alert_number: str
    source_system: str
    alert_type: str
    title: str
    description: Optional[str]
    level: str
    risk_level: str
    occurred_time: datetime
    location: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    facility_id: Optional[str]
    facility_name: Optional[str]
    parameter_snapshot: Optional[Dict[str, Any]]
    sensing_summary: Optional[Dict[str, Any]]
    ai_assessment: Optional[Dict[str, Any]]
    suggested_actions: Optional[List[str]]
    status: str
    handling_result: Optional[str]
    review_notes: Optional[str]
    is_simulated: Optional[bool]
    related_event_id: Optional[int]
    related_case_id: Optional[int]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


def _handle_error(exc: ValueError) -> None:
    message = str(exc)
    if message == "alert_not_found":
        raise HTTPException(status_code=404, detail="告警不存在")
    if message == "alert_number_conflict":
        raise HTTPException(status_code=409, detail="告警编号生成冲突，请重试")
    raise HTTPException(status_code=400, detail=message)


@router.get("/", response_model=List[AutomationAlertResponse])
def list_alerts(
    status: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """获取数智自动化告警列表。"""
    return AutomationAlertService.list_alerts(db, status=status, limit=limit)


@router.post("/", response_model=AutomationAlertResponse)
def create_alert(payload: AutomationAlertCreate, db: Session = Depends(get_db)):
    """创建数智自动化告警。"""
    try:
        return AutomationAlertService.create_alert(db, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        _handle_error(exc)


@router.post("/simulated", response_model=List[AutomationAlertResponse])
def seed_simulated_alerts(db: Session = Depends(get_db)):
    """写入或返回内置模拟告警，用于真实设备接入前联调。"""
    return AutomationAlertService.seed_simulated_alerts(db)


@router.get("/{alert_id:int}", response_model=AutomationAlertResponse)
def get_alert(alert_id: int, db: Session = Depends(get_db)):
    """获取单条告警。"""
    try:
        return AutomationAlertService.get_alert(db, alert_id)
    except ValueError as exc:
        _handle_error(exc)


@router.post("/{alert_id:int}/event")
def ensure_event(alert_id: int, db: Session = Depends(get_db)):
    """将告警写入事件中心。"""
    try:
        event = AutomationAlertService.ensure_event(db, alert_id)
        return {"alert_id": alert_id, "event_id": event.id, "message": "告警已生成事件"}
    except ValueError as exc:
        _handle_error(exc)


@router.post("/{alert_id:int}/false-alarm", response_model=AutomationAlertResponse)
def mark_false_alarm(
    alert_id: int,
    payload: Optional[FalseAlarmRequest] = Body(None),
    db: Session = Depends(get_db),
):
    """将告警标记为误报或设备异常。"""
    try:
        return AutomationAlertService.mark_false_alarm(db, alert_id, note=payload.note if payload else None)
    except ValueError as exc:
        _handle_error(exc)


@router.post("/{alert_id:int}/convert-to-case")
def convert_to_case(alert_id: int, db: Session = Depends(get_db)):
    """将告警转为案件。"""
    try:
        return AutomationAlertService.convert_to_case(db, alert_id)
    except ValueError as exc:
        _handle_error(exc)


@router.get("/{alert_id:int}/triage-pack")
def get_triage_pack(alert_id: int, db: Session = Depends(get_db)):
    """获取告警研判包：事实、AI依据、信息缺口、下一步和案件研判上下文。"""
    try:
        return AutomationAlertService.build_triage_pack(db, alert_id)
    except ValueError as exc:
        _handle_error(exc)
