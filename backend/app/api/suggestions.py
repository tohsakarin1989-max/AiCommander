from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.case import Case
from app.models.conclusion import Conclusion
from app.models.event import Event
from app.models.meeting import Meeting
from app.models.patrol import AreaRiskAssessment, PatrolRecord

router = APIRouter()

@router.get("/")
def get_suggestions(
    limit: int = 50,
    status: str = "open",
    db: Session = Depends(get_db),
):
    """生成跨模块待办建议，作为案件、会议、结论和巡逻之间的工作队列。"""
    now = datetime.utcnow()
    suggestions = []

    for case in (
        db.query(Case)
        .filter(Case.status.in_(["pending", "processing"]))
        .order_by(Case.created_at.desc())
        .limit(20)
        .all()
    ):
        missing_geo = case.latitude is None or case.longitude is None
        if missing_geo:
            suggestions.append({
                "id": f"case-geo-{case.id}",
                "type": "data_quality",
                "priority": "medium",
                "title": f"补全案件坐标：{case.case_number}",
                "description": "该案件缺少经纬度，暂不能进入地图研判、热点识别和巡逻路线计算。",
                "target_type": "case",
                "target_id": case.id,
                "action": "open_case",
                "status": "open",
                "created_at": now.isoformat(),
            })
        if not case.features:
            suggestions.append({
                "id": f"case-preprocess-{case.id}",
                "type": "analysis",
                "priority": "medium",
                "title": f"执行案件预处理：{case.case_number}",
                "description": "该案件尚未提取结构化特征，建议先预处理再进入串案、团伙或圆桌研判。",
                "target_type": "case",
                "target_id": case.id,
                "action": "preprocess_case",
                "status": "open",
                "created_at": now.isoformat(),
            })

    for conclusion in (
        db.query(Conclusion)
        .filter(Conclusion.status == "needs_review")
        .order_by(Conclusion.created_at.desc())
        .limit(20)
        .all()
    ):
        high_risk = conclusion.risk_level == "high"
        suggestions.append({
            "id": f"conclusion-review-{conclusion.id}",
            "type": "review",
            "priority": "high" if high_risk else "medium",
            "title": f"审核结论 #{conclusion.id}",
            "description": conclusion.summary or "该结论需要人工复核后再发布。",
            "target_type": "conclusion",
            "target_id": conclusion.id,
            "action": "review_conclusion",
            "status": "open",
            "created_at": str(conclusion.created_at or now),
        })

    for event in (
        db.query(Event)
        .filter(Event.related_case_id.is_(None))
        .order_by(Event.occurred_time.desc())
        .limit(20)
        .all()
    ):
        priority = "high" if event.risk_level in {"high", "critical"} else "medium"
        suggestions.append({
            "id": f"event-case-{event.id}",
            "type": "workflow",
            "priority": priority,
            "title": f"研判事件是否转案件：{event.event_number}",
            "description": event.title or event.description or "事件尚未关联案件，可视情况转入案件流程。",
            "target_type": "event",
            "target_id": event.id,
            "action": "convert_event_to_case",
            "status": "open",
            "created_at": str(event.created_at or now),
        })

    recent_cutoff = now - timedelta(days=7)
    for meeting in (
        db.query(Meeting)
        .filter(Meeting.status == "completed", Meeting.completed_at >= recent_cutoff)
        .order_by(Meeting.completed_at.desc())
        .limit(10)
        .all()
    ):
        has_conclusion = (
            db.query(Conclusion)
            .filter(Conclusion.meeting_id == meeting.meeting_id)
            .first()
            is not None
        )
        if not has_conclusion:
            suggestions.append({
                "id": f"meeting-conclusion-{meeting.meeting_id}",
                "type": "workflow",
                "priority": "medium",
                "title": f"从会议生成情报结论：{meeting.meeting_id}",
                "description": "该会议已完成但尚未沉淀为结论，建议进入结论工厂。",
                "target_type": "meeting",
                "target_id": meeting.meeting_id,
                "action": "generate_conclusion_from_meeting",
                "status": "open",
                "created_at": str(meeting.completed_at or meeting.created_at or now),
            })

    for risk in (
        db.query(AreaRiskAssessment)
        .filter(AreaRiskAssessment.risk_score >= 60)
        .order_by(AreaRiskAssessment.risk_score.desc())
        .limit(10)
        .all()
    ):
        active_patrol = (
            db.query(PatrolRecord)
            .filter(
                PatrolRecord.area_name == risk.area_name,
                PatrolRecord.status.in_(["planned", "in_progress"]),
            )
            .first()
        )
        if active_patrol:
            continue
        suggestions.append({
            "id": f"area-patrol-{risk.id}",
            "type": "patrol",
            "priority": "high" if risk.risk_score >= 80 else "medium",
            "title": f"安排重点巡逻：{risk.area_name}",
            "description": f"当前风险评分 {risk.risk_score:.0f}，建议生成定向巡逻计划。",
            "target_type": "area",
            "target_id": risk.area_name,
            "action": "create_patrol",
            "status": "open",
            "created_at": str(risk.updated_at or risk.created_at or now),
        })

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda item: (priority_rank.get(item["priority"], 9), item["created_at"]), reverse=False)

    filtered = [item for item in suggestions if item["status"] == status] if status else suggestions
    return {
        "suggestions": filtered[:limit],
        "total": len(filtered),
        "generated_at": now.isoformat(),
    }
