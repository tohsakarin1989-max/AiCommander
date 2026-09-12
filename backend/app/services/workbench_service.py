"""今日研判工作台：确定性分流与非敏感效率度量。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.agent_run import AgentApproval
from app.models.case import Case
from app.models.knowledge_asset import KnowledgeAsset
from app.models.workbench import WorkbenchTaskSession
from app.services.daily_workbench_service import information_gaps


TERMINAL_SESSION_STATUSES = {"completed", "abandoned"}
WORKBENCH_SAMPLE_THRESHOLD = 20


class WorkbenchError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.utcnow()


class WorkbenchService:
    """把现有案件闭环压缩成一个明确下一步，不替代人工判断。"""

    @staticmethod
    def normalize_internal_path(value: str) -> str:
        raw = (value or "").strip()
        parsed = urlsplit(raw)
        if (
            not raw.startswith("/")
            or raw.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or "\\" in parsed.path
            or any(ord(char) < 32 for char in raw)
        ):
            raise WorkbenchError("invalid_internal_path")
        path = parsed.path.rstrip("/") or "/"
        if len(path) > 300:
            raise WorkbenchError("invalid_internal_path")
        return path

    @staticmethod
    def today(
        db: Session,
        *,
        role: str,
        user_id: Optional[int],
        limit: int = 50,
    ) -> dict[str, Any]:
        cases = (
            db.query(Case)
            .order_by(Case.created_at.desc(), Case.id.desc())
            .all()
        )
        case_ids = [case.id for case in cases]
        latest_assets: dict[tuple[int, str], KnowledgeAsset] = {}
        if case_ids:
            assets = (
                db.query(KnowledgeAsset)
                .filter(KnowledgeAsset.source_case_id.in_(case_ids))
                .order_by(KnowledgeAsset.version.asc(), KnowledgeAsset.id.asc())
                .all()
            )
            for asset in assets:
                latest_assets[(asset.source_case_id, asset.asset_type)] = asset

        tasks: list[dict[str, Any]] = []
        stage_counts = defaultdict(int)
        completed = 0
        for case in cases:
            stage = WorkbenchService._next_case_stage(case, latest_assets)
            if stage == "completed":
                completed += 1
                continue
            stage_counts[stage] += 1
            tasks.append(WorkbenchService._task_payload(case, stage))

        priority_rank = {"high": 0, "medium": 1, "low": 2}
        stage_rank = {
            "data_review": 0,
            "experience_review": 1,
            "experience_generate": 2,
            "report_review": 3,
            "report_generate": 4,
        }
        tasks.sort(
            key=lambda item: (
                priority_rank[item["priority"]],
                stage_rank[item["stage"]],
                -item["source_id"],
            )
        )
        pending_approvals = (
            db.query(AgentApproval.id)
            .filter(AgentApproval.status == "pending")
            .count()
        )
        summary = {
            "total_cases": len(cases),
            "actionable_cases": len(tasks),
            "data_review": stage_counts["data_review"],
            "experience_review": (
                stage_counts["experience_generate"]
                + stage_counts["experience_review"]
            ),
            "report_review": (
                stage_counts["report_generate"] + stage_counts["report_review"]
            ),
            "completed": completed,
            "pending_approvals": pending_approvals,
        }
        return {
            "generated_at": utcnow().isoformat(),
            "role": role,
            "can_track_work": role in {"admin", "analyst"},
            "summary": summary,
            "pipeline": [
                {"stage": "data_review", "label": "数据核验", "count": summary["data_review"]},
                {"stage": "experience_review", "label": "经验沉淀", "count": summary["experience_review"]},
                {"stage": "report_review", "label": "报告复核", "count": summary["report_review"]},
                {"stage": "completed", "label": "无待确认事项", "count": summary["completed"]},
            ],
            "tasks": tasks[:limit],
            "active_session": WorkbenchService.active_session(db, user_id=user_id),
            "boundary": (
                "工作台只负责分流、记录和提示，案件事实、经验卡与报告仍由人工核验确认。"
                "经验卡和报告按需形成；无待确认事项或分析就绪不代表案件办结。"
            ),
        }

    @staticmethod
    def _next_case_stage(
        case: Case,
        latest_assets: dict[tuple[int, str], KnowledgeAsset],
    ) -> str:
        if information_gaps(case):
            return "data_review"

        experience = latest_assets.get((case.id, "experience_card"))
        if experience and experience.status not in {"confirmed", "archived"}:
            return "experience_review"

        report = latest_assets.get((case.id, "case_report"))
        if report and report.status not in {"confirmed", "archived"}:
            return "report_review"
        return "completed"

    @staticmethod
    def _task_payload(case: Case, stage: str) -> dict[str, Any]:
        definitions = {
            "data_review": {
                "priority": "high",
                "title": "补齐案件研判底座",
                "why": "案件缺少案发时间、地点依据或案情描述。",
                "impact": "缺口会影响时空关联、相似条件和后续报告可信度。",
                "next_action": "进入案件页核验字段，只保存人工确认后的内容。",
                "target_path": f"/cases?caseId={case.id}",
            },
            "experience_generate": {
                "priority": "medium",
                "title": "生成案件经验卡",
                "why": "案件数据已具备研判条件，但尚未形成独立经验资产。",
                "impact": "形成后可进入人工复核，并服务后续相似案例检索。",
                "next_action": "进入案件研判页生成经验卡草稿。",
                "target_path": f"/case-intelligence?caseId={case.id}",
            },
            "experience_review": {
                "priority": "high",
                "title": "复核案件经验卡",
                "why": "已有经验卡草稿等待人工确认或归档。",
                "impact": "未经确认的经验卡不会进入历史经验推荐。",
                "next_action": "核对事实、依据和适用边界后作出人工决定。",
                "target_path": f"/case-intelligence?caseId={case.id}",
            },
            "report_generate": {
                "priority": "medium",
                "title": "生成研判报告快照",
                "why": "经验资产已确认，但当前案件尚无版本化报告。",
                "impact": "报告快照可固定证据范围并支持回溯。",
                "next_action": "进入案件研判页选择经验依据并生成报告草稿。",
                "target_path": f"/case-intelligence?caseId={case.id}",
            },
            "report_review": {
                "priority": "high",
                "title": "复核研判报告",
                "why": "已有报告草稿等待人工确认或归档。",
                "impact": "确认前不得作为正式研判成果使用。",
                "next_action": "逐项核对事实、推断、建议及证据引用。",
                "target_path": f"/case-intelligence?caseId={case.id}",
            },
        }
        details = definitions[stage]
        return {
            "id": f"case:{case.id}:{stage}",
            "task_type": stage,
            "source_type": "case",
            "source_id": case.id,
            "case_number": case.case_number,
            "stage": stage,
            **details,
            "evidence_refs": [f"case:{case.id}", f"workflow-stage:{stage}"],
        }

    @staticmethod
    def start_session(
        db: Session,
        *,
        user_id: Optional[int],
        task_type: str,
        source_type: str,
        source_id: int,
        entry_path: str,
    ) -> tuple[WorkbenchTaskSession, bool]:
        normalized_path = WorkbenchService.normalize_internal_path(entry_path)
        case = db.query(Case).filter(Case.id == source_id).first()
        if source_type != "case" or not case:
            raise WorkbenchError("task_source_not_found")
        latest_assets: dict[tuple[int, str], KnowledgeAsset] = {}
        for asset in (
            db.query(KnowledgeAsset)
            .filter(KnowledgeAsset.source_case_id == case.id)
            .order_by(KnowledgeAsset.version.asc(), KnowledgeAsset.id.asc())
            .all()
        ):
            latest_assets[(asset.source_case_id, asset.asset_type)] = asset
        current_stage = WorkbenchService._next_case_stage(case, latest_assets)
        expected_path = "/cases" if current_stage == "data_review" else "/case-intelligence"
        if current_stage == "completed" or task_type != current_stage or normalized_path != expected_path:
            raise WorkbenchError("stale_workbench_task")
        active_query = db.query(WorkbenchTaskSession).filter(
            WorkbenchTaskSession.user_id == user_id,
            WorkbenchTaskSession.status == "active",
        )
        existing = active_query.filter(
            WorkbenchTaskSession.task_type == task_type,
            WorkbenchTaskSession.source_type == source_type,
            WorkbenchTaskSession.source_id == source_id,
        ).first()
        if existing:
            existing.last_activity_at = utcnow()
            db.commit()
            db.refresh(existing)
            return existing, False

        now = utcnow()
        for previous in active_query.all():
            previous.status = "abandoned"
            previous.active_slot = None
            previous.last_activity_at = now
            previous.completed_at = now

        session = WorkbenchTaskSession(
            user_id=user_id,
            task_type=task_type,
            source_type=source_type,
            source_id=source_id,
            status="active",
            active_slot=1,
            entry_path=normalized_path,
            last_path=normalized_path,
            page_transitions=0,
            started_at=now,
            last_activity_at=now,
        )
        db.add(session)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            concurrent = db.query(WorkbenchTaskSession).filter(
                WorkbenchTaskSession.user_id == user_id,
                WorkbenchTaskSession.status == "active",
            ).first()
            if (
                concurrent
                and concurrent.task_type == task_type
                and concurrent.source_type == source_type
                and concurrent.source_id == source_id
            ):
                return concurrent, False
            raise WorkbenchError("active_session_conflict") from exc
        db.refresh(session)
        return session, True

    @staticmethod
    def active_session(
        db: Session,
        *,
        user_id: Optional[int],
    ) -> Optional[dict[str, Any]]:
        session = (
            db.query(WorkbenchTaskSession)
            .filter(
                WorkbenchTaskSession.user_id == user_id,
                WorkbenchTaskSession.status == "active",
            )
            .order_by(WorkbenchTaskSession.started_at.desc())
            .first()
        )
        return WorkbenchService.session_payload(session) if session else None

    @staticmethod
    def record_event(
        db: Session,
        *,
        session_id: str,
        user_id: Optional[int],
        event: str,
        path: Optional[str] = None,
    ) -> WorkbenchTaskSession:
        session = db.query(WorkbenchTaskSession).filter(
            WorkbenchTaskSession.id == session_id,
            WorkbenchTaskSession.user_id == user_id,
        ).first()
        if not session:
            raise WorkbenchError("session_not_found")
        if session.status in TERMINAL_SESSION_STATUSES:
            return session

        now = utcnow()
        if event == "page_view":
            if path is None:
                raise WorkbenchError("invalid_internal_path")
            normalized_path = WorkbenchService.normalize_internal_path(path)
            if normalized_path != session.last_path:
                session.page_transitions += 1
                session.last_path = normalized_path
        elif event in TERMINAL_SESSION_STATUSES:
            session.status = event
            session.active_slot = None
            session.completed_at = now
        else:
            raise WorkbenchError("invalid_session_event")
        session.last_activity_at = now
        db.commit()
        db.refresh(session)
        return session

    @staticmethod
    def metrics(
        db: Session,
        *,
        role: str,
        user_id: Optional[int],
        days: int,
    ) -> dict[str, Any]:
        query = db.query(WorkbenchTaskSession).filter(
            WorkbenchTaskSession.started_at >= utcnow() - timedelta(days=days)
        )
        scope = "team" if role == "admin" else "self"
        if scope == "self":
            query = query.filter(WorkbenchTaskSession.user_id == user_id)
        sessions = query.order_by(WorkbenchTaskSession.started_at.desc()).limit(1000).all()

        def aggregate(items: list[WorkbenchTaskSession]) -> dict[str, Any]:
            completed = [item for item in items if item.status == "completed"]
            abandoned = [item for item in items if item.status == "abandoned"]
            durations = [
                max(0, int((item.completed_at - item.started_at).total_seconds()))
                for item in items
                if item.completed_at and item.started_at
            ]
            return {
                "started": len(items),
                "completed": len(completed),
                "abandoned": len(abandoned),
                "active": sum(item.status == "active" for item in items),
                "completion_rate": round(len(completed) / len(items), 3) if items else 0,
                "avg_duration_seconds": (
                    round(sum(durations) / len(durations)) if durations else None
                ),
                "avg_page_transitions": (
                    round(sum(item.page_transitions or 0 for item in items) / len(items), 1)
                    if items
                    else None
                ),
            }

        grouped: dict[str, list[WorkbenchTaskSession]] = defaultdict(list)
        for session in sessions:
            grouped[session.task_type].append(session)
        return {
            "scope": scope,
            "days": days,
            "totals": aggregate(sessions),
            "by_task_type": [
                {"task_type": task_type, **aggregate(items)}
                for task_type, items in sorted(grouped.items())
            ],
            "business_acceptance_status": (
                "measurable" if len(sessions) >= WORKBENCH_SAMPLE_THRESHOLD else "insufficient_sample"
            ),
            "sample_threshold": WORKBENCH_SAMPLE_THRESHOLD,
            "measurement_boundary": "仅统计工作台会话耗时和页面跳转，不采集案情正文、人员、井名或坐标。",
        }

    @staticmethod
    def session_payload(session: WorkbenchTaskSession) -> dict[str, Any]:
        return {
            "id": session.id,
            "task_type": session.task_type,
            "source_type": session.source_type,
            "source_id": session.source_id,
            "status": session.status,
            "entry_path": session.entry_path,
            "last_path": session.last_path,
            "page_transitions": session.page_transitions or 0,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "last_activity_at": (
                session.last_activity_at.isoformat() if session.last_activity_at else None
            ),
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        }
