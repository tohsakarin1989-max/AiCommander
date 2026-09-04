"""Agent Lab 运行、事件、审批和回放 API。"""
from __future__ import annotations

import json
from time import monotonic, sleep
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent_runtime.service import AgentReplayConflict, AgentRunService, FINAL_RUN_STATUSES
from app.config import settings
from app.database import get_db
from app.models.agent_run import AgentApproval, AgentArtifact, AgentEvent, AgentRun
from app.models.jurisdiction import JurisdictionAsset
from app.services.map_steward_service import MapStewardPilotService


router = APIRouter()


class AgentRunCreate(BaseModel):
    task_type: Literal[
        "case_data_quality",
        "map_data_quality",
        "dual_domain_analysis",
        "evidence_report",
    ]
    query: str = Field(..., min_length=1, max_length=2000)
    case_ids: list[int] = Field(default_factory=list, max_length=30)
    asset_ids: list[int] = Field(default_factory=list, max_length=500)


class AgentApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    comment: Optional[str] = Field(default=None, max_length=1000)


def dispatch_agent_run(run_id: str) -> None:
    import redis

    from app.tasks.agent_tasks import execute_agent_run_task

    queue = redis.Redis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=0.3,
        socket_timeout=0.3,
    )
    try:
        queue.ping()
    finally:
        queue.close()
    execute_agent_run_task.apply_async(
        args=[run_id],
        queue=settings.AGENT_REDIS_QUEUE,
        retry=False,
    )


def _principal(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None and settings.AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="请先登录")
    return principal


def _principal_user_id(principal) -> int | None:
    return getattr(principal, "user_id", getattr(principal, "id", None))


def _require_lab(request: Request, *, admin_only: bool = False):
    if not settings.ENABLE_AGENT_LAB or settings.AGENT_MODE == "off":
        raise HTTPException(status_code=404, detail="Agent Lab 未启用")
    principal = _principal(request)
    role = getattr(principal, "role", "admin" if not settings.AUTH_REQUIRED else None)
    if role not in {"admin", "analyst"}:
        raise HTTPException(status_code=403, detail="当前账号无权访问 Agent Lab")
    if admin_only and role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")
    return principal


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_agent_run(
    payload: AgentRunCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _require_lab(request)
    principal_user_id = _principal_user_id(principal)
    if settings.AGENT_MODE == "assist":
        if payload.task_type != "map_data_quality":
            raise HTTPException(
                status_code=403,
                detail="v2.2受控辅助模式仅开放地图数据管家",
            )
        if not payload.asset_ids:
            raise HTTPException(status_code=422, detail="受控辅助模式必须明确选择地图资源")
        if payload.case_ids:
            raise HTTPException(status_code=422, detail="地图数据管家试用不得混入案件范围")
        if len(set(payload.asset_ids)) > settings.AGENT_MAP_PILOT_MAX_ASSETS:
            raise HTTPException(
                status_code=422,
                detail=f"单次最多选择{settings.AGENT_MAP_PILOT_MAX_ASSETS}个地图资源",
            )
        selected_asset_ids = set(payload.asset_ids)
        available_asset_count = db.query(JurisdictionAsset.id).filter(
            JurisdictionAsset.id.in_(selected_asset_ids),
            JurisdictionAsset.status == "active",
        ).count()
        if available_asset_count != len(selected_asset_ids):
            raise HTTPException(status_code=422, detail="所选地图资源不存在或已失效")
        control = MapStewardPilotService.get_control(db)
        if not control.enabled:
            raise HTTPException(status_code=409, detail="地图数据管家试用尚未开启")
        if not MapStewardPilotService.is_pilot_user(control, principal_user_id):
            raise HTTPException(status_code=403, detail="当前账号未被加入地图数据管家试用名单")
    run = AgentRunService.create_run(
        db,
        task_type=payload.task_type,
        query=payload.query,
        case_ids=payload.case_ids,
        asset_ids=payload.asset_ids,
        mode=settings.AGENT_MODE,
        created_by=principal_user_id,
    )
    try:
        dispatch_agent_run(run.id)
    except Exception as exc:
        AgentRunService.mark_dispatch_failed(db, run.id, exc)
        raise HTTPException(status_code=503, detail="Agent 队列暂不可用，核心业务不受影响") from exc
    return _run_payload(AgentRunService.get_run(db, run.id), detail=True)


@router.get("")
def list_agent_runs(
    request: Request,
    skip: int = 0,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _require_lab(request)
    return [_run_payload(run, detail=False) for run in AgentRunService.list_runs(db, skip=skip, limit=limit)]


@router.get("/{run_id}")
def get_agent_run(run_id: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_lab(request)
    try:
        return _run_payload(AgentRunService.get_run(db, run_id), detail=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent 任务不存在") from exc


@router.get("/{run_id}/events")
def get_agent_events(
    run_id: str,
    request: Request,
    stream: bool = False,
    after_sequence: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    _require_lab(request)
    try:
        run = AgentRunService.get_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent 任务不存在") from exc
    if not stream:
        return [_event_payload(item) for item in run.events if item.sequence > after_sequence]

    def event_stream():
        cursor = after_sequence
        deadline = monotonic() + settings.AGENT_TIMEOUT_SECONDS + 30
        while True:
            db.expire_all()
            fresh_events = (
                db.query(AgentEvent)
                .filter(AgentEvent.run_id == run_id, AgentEvent.sequence > cursor)
                .order_by(AgentEvent.sequence.asc())
                .all()
            )
            for item in fresh_events:
                event = _event_payload(item)
                cursor = item.sequence
                yield (
                    f"id: {event['sequence']}\n"
                    f"event: {event['event_type']}\n"
                    f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                )

            current_status = db.query(AgentRun.status).filter(AgentRun.id == run_id).scalar()
            if current_status in FINAL_RUN_STATUSES or current_status == "waiting_approval":
                yield f"event: stream_end\ndata: {json.dumps({'status': current_status})}\n\n"
                return
            if monotonic() >= deadline:
                yield "event: stream_timeout\ndata: {}\n\n"
                return
            yield ": keepalive\n\n"
            sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{run_id}/cancel")
def cancel_agent_run(run_id: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    principal = _require_lab(request)
    try:
        run = AgentRunService.cancel_run(db, run_id, actor_user_id=_principal_user_id(principal))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent 任务不存在") from exc
    return _run_payload(run, detail=True)


@router.post("/{run_id}/approvals/{approval_id}")
def review_agent_approval(
    run_id: str,
    approval_id: str,
    payload: AgentApprovalDecision,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _require_lab(request, admin_only=True)
    try:
        run = AgentRunService.get_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent 任务不存在") from exc
    belongs_to_run = db.query(AgentApproval).filter(
        AgentApproval.id == approval_id,
        AgentApproval.run_id == run.id,
    ).first()
    if belongs_to_run is None:
        raise HTTPException(status_code=404, detail="审批不属于当前 Agent 任务")
    if (
        payload.decision == "approve"
        and run.mode == "assist"
        and belongs_to_run.status == "pending"
    ):
        if run.task_type != "map_data_quality":
            raise HTTPException(status_code=403, detail="v2.2不允许辅助模式修改案件或研判结论")
        control = MapStewardPilotService.get_control(db)
        if not control.enabled or control.mutations_suspended:
            raise HTTPException(status_code=409, detail="地图数据管家候选写入已暂停")
        if not MapStewardPilotService.is_pilot_user(control, run.created_by):
            raise HTTPException(status_code=403, detail="任务发起人已不在地图数据管家试用名单")
        if not settings.AGENT_MUTATIONS_ENABLED:
            raise HTTPException(status_code=409, detail="全局写入保护仍处于关闭状态")
    try:
        approval = AgentRunService.review_approval(
            db,
            approval_id=approval_id,
            decision=payload.decision,
            decided_by=_principal_user_id(principal),
            comment=payload.comment,
            allow_mutations=settings.AGENT_MUTATIONS_ENABLED,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent 审批不存在") from exc
    return _approval_payload(approval)


@router.post("/{run_id}/replay", status_code=status.HTTP_202_ACCEPTED)
def replay_agent_run(run_id: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    principal = _require_lab(request, admin_only=True)
    try:
        original = AgentRunService.get_run(db, run_id)
        principal_user_id = _principal_user_id(principal)
        if original.mode == "assist":
            control = MapStewardPilotService.get_control(db)
            if original.task_type != "map_data_quality":
                raise HTTPException(status_code=403, detail="v2.2受控辅助模式仅开放地图数据管家")
            if not control.enabled:
                raise HTTPException(status_code=409, detail="地图数据管家试用尚未开启")
            if not MapStewardPilotService.is_pilot_user(control, principal_user_id):
                raise HTTPException(status_code=403, detail="当前管理员未被加入地图数据管家试用名单")
            replay_asset_ids = set(original.asset_ids or [])
            if original.case_ids or not replay_asset_ids:
                raise HTTPException(status_code=422, detail="旧任务不符合v2.2地图资源限界，不能重放")
            if len(replay_asset_ids) > settings.AGENT_MAP_PILOT_MAX_ASSETS:
                raise HTTPException(status_code=422, detail="旧任务超出地图资源试用上限，不能重放")
            available_asset_count = db.query(JurisdictionAsset.id).filter(
                JurisdictionAsset.id.in_(replay_asset_ids),
                JurisdictionAsset.status == "active",
            ).count()
            if available_asset_count != len(replay_asset_ids):
                raise HTTPException(status_code=422, detail="旧任务包含不存在或已失效的地图资源")
        replay = AgentRunService.replay_run(db, run_id, created_by=principal_user_id)
    except AgentReplayConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="源数据版本已变化，请新建分析任务，不得沿用旧版本重放",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent 任务不存在") from exc
    try:
        dispatch_agent_run(replay.id)
    except Exception as exc:
        AgentRunService.mark_dispatch_failed(db, replay.id, exc)
        raise HTTPException(status_code=503, detail="Agent 队列暂不可用，核心业务不受影响") from exc
    return _run_payload(AgentRunService.get_run(db, replay.id), detail=True)


def _run_payload(run: AgentRun, *, detail: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": run.id,
        "task_type": run.task_type,
        "query": run.query,
        "case_ids": run.case_ids or [],
        "asset_ids": run.asset_ids or [],
        "mode": run.mode,
        "status": run.status,
        "model_provider": run.model_provider,
        "model_name": run.model_name,
        "data_version": run.data_version,
        "result_summary": run.result_summary or {},
        "error_message": run.error_message,
        "attempt_count": run.attempt_count,
        "created_by": run.created_by,
        "replay_of_id": run.replay_of_id,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
        "artifact_count": len(run.artifacts),
        "pending_approval_count": sum(1 for item in run.approvals if item.status == "pending"),
    }
    if detail:
        payload["events"] = [_event_payload(item) for item in run.events]
        payload["artifacts"] = [_artifact_payload(item) for item in run.artifacts]
        payload["approvals"] = [_approval_payload(item) for item in run.approvals]
    return payload


def _event_payload(event: AgentEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "status": event.status,
        "actor_type": event.actor_type,
        "actor_name": event.actor_name,
        "input_summary": event.input_summary or {},
        "output_summary": event.output_summary or {},
        "evidence_refs": event.evidence_refs or [],
        "error_message": event.error_message,
        "duration_ms": event.duration_ms,
        "created_at": _iso(event.created_at),
    }


def _artifact_payload(artifact: AgentArtifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "run_id": artifact.run_id,
        "artifact_type": artifact.artifact_type,
        "version": artifact.version,
        "content": artifact.content or {},
        "evidence_refs": artifact.evidence_refs or [],
        "source_signature": artifact.source_signature,
        "created_at": _iso(artifact.created_at),
    }


def _approval_payload(approval: AgentApproval) -> dict[str, Any]:
    return {
        "id": approval.id,
        "run_id": approval.run_id,
        "artifact_id": approval.artifact_id,
        "action_type": approval.action_type,
        "target_type": approval.target_type,
        "target_id": approval.target_id,
        "candidate_patch": approval.candidate_patch or {},
        "status": approval.status,
        "decision_comment": approval.decision_comment,
        "execution_result": approval.execution_result or {},
        "expires_at": _iso(approval.expires_at),
        "decided_at": _iso(approval.decided_at),
        "executed_at": _iso(approval.executed_at),
        "created_at": _iso(approval.created_at),
    }


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None
