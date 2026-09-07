"""Agent 运行记录、审批、取消和回放服务。"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any, Iterable, Optional
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.agent_run import AgentApproval, AgentEvent, AgentRun
from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.agent_runtime.tools import asset_source_signature
from app.services.jurisdiction_service import JurisdictionService


FINAL_RUN_STATUSES = {"completed", "failed", "cancelled", "expired", "degraded"}


class AgentReplayConflict(ValueError):
    pass


class AgentRunService:
    @staticmethod
    def create_run(
        db: Session,
        *,
        task_type: str,
        query: str,
        case_ids: Iterable[int],
        asset_ids: Iterable[int],
        mode: str,
        created_by: Optional[int],
        replay_of_id: Optional[str] = None,
    ) -> AgentRun:
        normalized_cases = list(dict.fromkeys(int(item) for item in case_ids))[:30]
        normalized_assets = list(dict.fromkeys(int(item) for item in asset_ids))[:500]
        run = AgentRun(
            id=str(uuid4()),
            task_type=task_type,
            query=query.strip(),
            case_ids=normalized_cases,
            asset_ids=normalized_assets,
            mode=mode,
            status="queued",
            data_version=AgentRunService._data_version(
                db,
                task_type=task_type,
                case_ids=normalized_cases,
                asset_ids=normalized_assets,
            ),
            input_payload={
                "case_count": len(normalized_cases),
                "asset_count": len(normalized_assets),
                "query_length": len(query.strip()),
            },
            result_summary={},
            runtime_state={"runtime_version": 1},
            created_by=created_by,
            replay_of_id=replay_of_id,
        )
        db.add(run)
        db.flush()
        AgentRunService.append_event(
            db,
            run,
            event_type="run_created",
            status="queued",
            actor_type="user" if created_by else "system",
            actor_user_id=created_by,
            input_summary=run.input_payload,
        )
        db.commit()
        return AgentRunService.get_run(db, run.id)

    @staticmethod
    def get_run(db: Session, run_id: str) -> AgentRun:
        run = (
            db.query(AgentRun)
            .options(
                joinedload(AgentRun.events),
                joinedload(AgentRun.artifacts),
                joinedload(AgentRun.approvals),
            )
            .filter(AgentRun.id == run_id)
            .first()
        )
        if run is None:
            raise ValueError("agent_run_not_found")
        return run

    @staticmethod
    def list_runs(db: Session, *, limit: int = 50, skip: int = 0) -> list[AgentRun]:
        return (
            db.query(AgentRun)
            .options(joinedload(AgentRun.artifacts), joinedload(AgentRun.approvals))
            .order_by(AgentRun.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    @staticmethod
    def append_event(
        db: Session,
        run: AgentRun,
        *,
        event_type: str,
        status: Optional[str] = None,
        actor_type: str = "system",
        actor_name: Optional[str] = None,
        actor_user_id: Optional[int] = None,
        input_summary: Optional[dict[str, Any]] = None,
        output_summary: Optional[dict[str, Any]] = None,
        evidence_refs: Optional[list[str]] = None,
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> AgentEvent:
        # PostgreSQL 下锁住所属运行记录，避免取消、审批与 Worker 同时追加事件时
        # 争用同一 sequence；SQLite 测试环境会安全地忽略 FOR UPDATE。
        db.query(AgentRun.id).filter(AgentRun.id == run.id).with_for_update().one()
        last_sequence = db.query(func.max(AgentEvent.sequence)).filter(
            AgentEvent.run_id == run.id
        ).scalar() or 0
        event = AgentEvent(
            run_id=run.id,
            sequence=last_sequence + 1,
            event_type=event_type,
            status=status or run.status,
            actor_type=actor_type,
            actor_name=actor_name,
            actor_user_id=actor_user_id,
            input_summary=input_summary or {},
            output_summary=output_summary or {},
            evidence_refs=evidence_refs or [],
            error_message=error_message,
            duration_ms=duration_ms,
        )
        db.add(event)
        db.flush()
        return event

    @staticmethod
    def cancel_run(db: Session, run_id: str, *, actor_user_id: Optional[int]) -> AgentRun:
        run = AgentRunService.get_run(db, run_id)
        if run.status in FINAL_RUN_STATUSES:
            return run
        run.status = "cancelled"
        run.completed_at = datetime.utcnow()
        AgentRunService.append_event(
            db,
            run,
            event_type="run_cancelled",
            status="cancelled",
            actor_type="user",
            actor_user_id=actor_user_id,
        )
        db.commit()
        return AgentRunService.get_run(db, run_id)

    @staticmethod
    def suspend_map_pilot(
        db: Session,
        *,
        actor_user_id: Optional[int],
        reason: str,
    ) -> dict[str, int]:
        """停止地图试用运行并使所有待审批候选失效，不触碰正式地图数据。"""
        now = datetime.utcnow()
        runs = db.query(AgentRun).filter(
            AgentRun.task_type == "map_data_quality",
            AgentRun.mode == "assist",
            AgentRun.status.in_({
                "queued",
                "planning",
                "running",
                "verifying",
                "waiting_approval",
            }),
        ).all()
        expired_approvals = 0
        for run in runs:
            approvals = db.query(AgentApproval).filter(
                AgentApproval.run_id == run.id,
                AgentApproval.status == "pending",
            ).all()
            for approval in approvals:
                approval.status = "expired"
                approval.decided_at = now
                approval.execution_result = {
                    "applied": False,
                    "reason": "map_pilot_suspended",
                }
                expired_approvals += 1
            run.status = "cancelled"
            run.completed_at = now
            AgentRunService.append_event(
                db,
                run,
                event_type="pilot_suspended",
                status="cancelled",
                actor_type="user",
                actor_user_id=actor_user_id,
                input_summary={"reason": reason.strip()[:500]},
                output_summary={"expired_approval_count": len(approvals)},
            )
        db.commit()
        return {"cancelled_run_count": len(runs), "expired_approval_count": expired_approvals}

    @staticmethod
    def suspend_case_pilot(
        db: Session,
        *,
        actor_user_id: Optional[int],
        reason: str,
    ) -> dict[str, int]:
        """停止案件只读试用运行，不触碰正式案件数据。"""
        now = datetime.utcnow()
        runs = db.query(AgentRun).filter(
            AgentRun.task_type == "case_data_quality",
            AgentRun.mode == "assist",
            AgentRun.status.in_({
                "queued",
                "planning",
                "running",
                "verifying",
                "waiting_approval",
            }),
        ).all()
        for run in runs:
            run.status = "cancelled"
            run.completed_at = now
            AgentRunService.append_event(
                db,
                run,
                event_type="case_pilot_suspended",
                status="cancelled",
                actor_type="user",
                actor_user_id=actor_user_id,
                input_summary={"reason": reason.strip()[:500]},
                output_summary={"formal_case_changes": 0},
            )
        db.commit()
        return {"cancelled_run_count": len(runs)}

    @staticmethod
    def replay_run(db: Session, run_id: str, *, created_by: Optional[int]) -> AgentRun:
        original = AgentRunService.get_run(db, run_id)
        current_data_version = AgentRunService._data_version(
            db,
            task_type=original.task_type,
            case_ids=list(original.case_ids or []),
            asset_ids=list(original.asset_ids or []),
        )
        if current_data_version != original.data_version:
            raise AgentReplayConflict("agent_replay_data_version_changed")
        return AgentRunService.create_run(
            db,
            task_type=original.task_type,
            query=original.query,
            case_ids=original.case_ids or [],
            asset_ids=original.asset_ids or [],
            mode=original.mode,
            created_by=created_by,
            replay_of_id=original.id,
        )

    @staticmethod
    def review_approval(
        db: Session,
        *,
        approval_id: str,
        decision: str,
        decided_by: Optional[int],
        comment: Optional[str],
        allow_mutations: bool,
    ) -> AgentApproval:
        approval = db.query(AgentApproval).filter(AgentApproval.id == approval_id).first()
        if approval is None:
            raise ValueError("agent_approval_not_found")
        if approval.status != "pending":
            return approval

        now = datetime.utcnow()
        expires_at = AgentRunService._naive_utc(approval.expires_at)
        if expires_at and expires_at <= now:
            approval.status = "expired"
            approval.decided_at = now
            approval.execution_result = {"applied": False, "reason": "approval_expired"}
            run = AgentRunService.get_run(db, approval.run_id)
            AgentRunService.append_event(
                db,
                run,
                event_type="approval_expired",
                status=run.status,
                actor_type="system",
                output_summary={"approval_id": approval.id},
            )
            db.flush()
            AgentRunService._close_run_if_approvals_expired(db, run, now)
            db.commit()
            return approval

        approval.decided_by = decided_by
        approval.decision_comment = comment
        approval.decided_at = now
        run = AgentRunService.get_run(db, approval.run_id)
        if decision == "reject":
            approval.status = "rejected"
            approval.execution_result = {"applied": False, "reason": "rejected_by_reviewer"}
        elif decision == "approve":
            approval.status = "approved"
            approval.execution_result = AgentRunService._execute_approved_action(
                db,
                run=run,
                approval=approval,
                allow_mutations=allow_mutations,
            )
            if approval.execution_result.get("applied"):
                approval.status = "executed"
                approval.executed_at = now
        else:
            raise ValueError("invalid_approval_decision")

        AgentRunService.append_event(
            db,
            run,
            event_type="approval_decided",
            status=run.status,
            actor_type="user",
            actor_user_id=decided_by,
            input_summary={"approval_id": approval.id, "decision": decision},
            output_summary=approval.execution_result,
            evidence_refs=[f"{approval.target_type}:{approval.target_id}"],
        )
        db.flush()
        pending_count = db.query(AgentApproval).filter(
            AgentApproval.run_id == run.id,
            AgentApproval.status == "pending",
        ).count()
        if pending_count == 0 and run.status == "waiting_approval":
            run.status = "completed"
            run.completed_at = now
            AgentRunService.append_event(
                db,
                run,
                event_type="run_completed",
                status="completed",
                output_summary={"approval_flow_completed": True},
            )
        db.commit()
        return db.query(AgentApproval).filter(AgentApproval.id == approval.id).one()

    @staticmethod
    def mark_dispatch_failed(db: Session, run_id: str, error: Exception) -> AgentRun:
        run = AgentRunService.get_run(db, run_id)
        run.status = "failed"
        run.error_message = "Agent 队列暂不可用"
        run.completed_at = datetime.utcnow()
        AgentRunService.append_event(
            db,
            run,
            event_type="dispatch_failed",
            status="failed",
            error_message=type(error).__name__,
        )
        db.commit()
        return AgentRunService.get_run(db, run_id)

    @staticmethod
    def mark_execution_failed(db: Session, run_id: str, *, reason: str) -> AgentRun:
        """记录可由队列重试或管理员重放的执行失败。"""
        run = AgentRunService.get_run(db, run_id)
        run.status = "failed"
        run.error_message = reason
        run.completed_at = datetime.utcnow()
        AgentRunService.append_event(
            db,
            run,
            event_type="run_failed",
            status="failed",
            error_message=reason,
            output_summary={"retryable": True},
        )
        db.commit()
        return AgentRunService.get_run(db, run_id)

    @staticmethod
    def expire_stale_approvals(db: Session, *, now: Optional[datetime] = None) -> int:
        """周期关闭过期审批，绝不执行候选写入。"""
        current_time = now or datetime.utcnow()
        approvals = (
            db.query(AgentApproval)
            .filter(
                AgentApproval.status == "pending",
                AgentApproval.expires_at.isnot(None),
                AgentApproval.expires_at <= current_time,
            )
            .order_by(AgentApproval.run_id.asc(), AgentApproval.created_at.asc())
            .all()
        )
        affected_runs: dict[str, AgentRun] = {}
        for approval in approvals:
            approval.status = "expired"
            approval.decided_at = current_time
            approval.execution_result = {"applied": False, "reason": "approval_expired"}
            run = affected_runs.get(approval.run_id)
            if run is None:
                run = AgentRunService.get_run(db, approval.run_id)
                affected_runs[approval.run_id] = run
            AgentRunService.append_event(
                db,
                run,
                event_type="approval_expired",
                status=run.status,
                output_summary={"approval_id": approval.id},
            )

        db.flush()
        for run in affected_runs.values():
            AgentRunService._close_run_if_approvals_expired(db, run, current_time)
        if approvals:
            db.commit()
        return len(approvals)

    @staticmethod
    def _close_run_if_approvals_expired(
        db: Session,
        run: AgentRun,
        now: datetime,
    ) -> None:
        pending_count = db.query(AgentApproval).filter(
            AgentApproval.run_id == run.id,
            AgentApproval.status == "pending",
        ).count()
        if pending_count == 0 and run.status == "waiting_approval":
            run.status = "expired"
            run.completed_at = now
            AgentRunService.append_event(
                db,
                run,
                event_type="run_expired",
                status="expired",
                output_summary={"reason": "approval_window_elapsed"},
            )

    @staticmethod
    def _execute_approved_action(
        db: Session,
        *,
        run: AgentRun,
        approval: AgentApproval,
        allow_mutations: bool,
    ) -> dict[str, Any]:
        if not allow_mutations:
            return {"applied": False, "reason": "agent_mutations_disabled"}
        if run.mode != "assist":
            return {"applied": False, "reason": "run_not_in_assist_mode"}
        if approval.action_type != "asset_patch" or approval.target_type != "jurisdiction_asset":
            return {"applied": False, "reason": "action_not_whitelisted"}

        patch = dict(approval.candidate_patch or {})
        if not patch or not set(patch).issubset({"name", "geometry"}):
            return {"applied": False, "reason": "patch_fields_not_whitelisted"}
        asset = db.query(JurisdictionAsset).filter(
            JurisdictionAsset.id == approval.target_id
        ).first()
        if asset is None:
            return {"applied": False, "reason": "asset_not_found"}
        if asset.verified:
            return {"applied": False, "reason": "verified_asset_is_protected"}
        if asset_source_signature(asset) != approval.source_signature:
            return {"applied": False, "reason": "source_changed_since_analysis"}

        if "name" in patch:
            current_name = asset.name or ""
            candidate_name = patch["name"]
            if (
                not isinstance(candidate_name, str)
                or candidate_name != current_name.strip()
                or candidate_name == current_name
            ):
                return {"applied": False, "reason": "candidate_name_outside_policy"}
        if "geometry" in patch:
            if (
                asset.geometry_type != "point"
                or asset.latitude is None
                or asset.longitude is None
                or not -90 <= asset.latitude <= 90
                or not -180 <= asset.longitude <= 180
            ):
                return {"applied": False, "reason": "candidate_geometry_outside_policy"}
            expected_geometry = {
                "type": "Point",
                "coordinates": [asset.longitude, asset.latitude],
            }
            if patch["geometry"] != expected_geometry or patch["geometry"] == asset.geometry:
                return {"applied": False, "reason": "candidate_geometry_outside_policy"}

        changed_fields = sorted(patch)
        JurisdictionService.update_asset(
            db,
            asset.id,
            patch,
            commit=False,
            sync_point_geometry=False,
        )
        return {
            "applied": True,
            "target_type": approval.target_type,
            "target_id": asset.id,
            "fields": changed_fields,
        }

    @staticmethod
    def _data_version(
        db: Session,
        *,
        task_type: str,
        case_ids: list[int],
        asset_ids: list[int],
    ) -> str:
        cases = (
            db.query(Case).filter(Case.id.in_(case_ids)).order_by(Case.id.asc()).all()
            if case_ids else []
        )
        assets = (
            db.query(JurisdictionAsset)
            .filter(JurisdictionAsset.id.in_(asset_ids))
            .order_by(JurisdictionAsset.id.asc())
            .all()
            if asset_ids else []
        )
        case_scope: dict[str, Any]
        if case_ids:
            case_scope = {
                "mode": "selected",
                "items": [
                    [case.id, case.updated_at.isoformat() if case.updated_at else None]
                    for case in cases
                ],
            }
        else:
            count, max_id, max_updated_at = db.query(
                func.count(Case.id),
                func.max(Case.id),
                func.max(Case.updated_at),
            ).one()
            case_scope = {
                "mode": "global",
                "count": count,
                "max_id": max_id,
                "max_updated_at": max_updated_at.isoformat() if max_updated_at else None,
            }

        asset_scope: dict[str, Any]
        if asset_ids:
            asset_scope = {
                "mode": "selected",
                "items": [
                    [asset.id, asset_source_signature(asset)]
                    for asset in assets
                ],
            }
        else:
            count, max_id, max_updated_at = db.query(
                func.count(JurisdictionAsset.id),
                func.max(JurisdictionAsset.id),
                func.max(JurisdictionAsset.updated_at),
            ).one()
            asset_scope = {
                "mode": "global",
                "count": count,
                "max_id": max_id,
                "max_updated_at": max_updated_at.isoformat() if max_updated_at else None,
            }
        payload = {
            "task_type": task_type,
            "cases": case_scope,
            "assets": asset_scope,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
