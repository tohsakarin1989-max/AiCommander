from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models.automation_alert import AutomationAlert
from app.models.case import Case
from app.models.conclusion import Conclusion
from app.models.event import Event
from app.models.meeting import Meeting
from app.models.patrol import AreaRiskAssessment
from app.services.case_automation_service import CaseAutomationService
from app.services.case_quality_service import CaseQualityService

router = APIRouter()


def _iso(value, fallback: datetime) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if value:
        return str(value)
    return fallback.isoformat()


def _existing_experience_card(case: Case) -> dict:
    features = case.features if isinstance(case.features, dict) else {}
    intelligence = features.get("intelligence") if isinstance(features.get("intelligence"), dict) else {}
    card = intelligence.get("experience_card") if isinstance(intelligence.get("experience_card"), dict) else {}
    return card


def _has_experience_card_inputs(case: Case) -> bool:
    return bool(
        (case.description and len(case.description.strip()) >= 10)
        or case.location
        or case.case_type
        or case.features
    )


@router.get("/")
def get_suggestions(
    limit: int = 50,
    status: str = "open",
    db: Session = Depends(get_db),
):
    """生成跨模块研判待办，统一收纳案件、告警、结论、报告和核算缺口。"""
    now = datetime.utcnow()
    suggestions = []

    def add_item(
        *,
        item_id: str,
        item_type: str,
        priority: str,
        title: str,
        description: str,
        target_type: str,
        target_id,
        action: str,
        created_at=None,
        meta=None,
    ):
        suggestions.append({
            "id": item_id,
            "type": item_type,
            "priority": priority,
            "title": title,
            "description": description,
            "target_type": target_type,
            "target_id": target_id,
            "action": action,
            "status": "open",
            "created_at": _iso(created_at, now),
            "meta": meta or {},
        })

    for case in (
        db.query(Case)
        .filter(Case.status.in_(["pending", "processing"]))
        .order_by(Case.created_at.desc())
        .limit(20)
        .all()
    ):
        missing_geo = case.latitude is None or case.longitude is None
        if missing_geo:
            add_item(
                item_id=f"case-geo-{case.id}",
                item_type="data_quality",
                priority="medium",
                title=f"补全案件坐标：{case.case_number}",
                description="该案件缺少经纬度，暂不能进入地图研判、热点识别和路径条件复盘。",
                target_type="case",
                target_id=case.id,
                action="open_case",
                created_at=case.updated_at or case.created_at,
            )
        if not case.features:
            add_item(
                item_id=f"case-preprocess-{case.id}",
                item_type="analysis",
                priority="medium",
                title=f"执行案件预处理：{case.case_number}",
                description="该案件尚未提取结构化特征，建议先预处理再进入串案、链条或圆桌研判。",
                target_type="case",
                target_id=case.id,
                action="preprocess_case",
                created_at=case.updated_at or case.created_at,
            )

        quality = case.quality_issues or CaseQualityService.evaluate_case(db, case)
        if quality.get("level") == "low" or (quality.get("score") or 100) < 70:
            add_item(
                item_id=f"case-quality-{case.id}",
                item_type="data_quality",
                priority="high" if (quality.get("score") or 0) < 50 else "medium",
                title=f"复核案件质量：{case.case_number}",
                description="该案件存在信息质量缺口，可能影响后续研判、报告引用和复盘沉淀。",
                target_type="case",
                target_id=case.id,
                action="open_case",
                created_at=case.quality_updated_at or case.updated_at or case.created_at,
                meta={
                    "score": quality.get("score"),
                    "missing_count": len(quality.get("missing_required") or []),
                },
            )

        if settings.ENABLE_BONUS_ACCOUNTING:
            try:
                bonus = CaseAutomationService.build_bonus_assessment(db, case)
                calculation_gate = bonus.get("calculation_gate") or {}
                material_gate = bonus.get("material_gate") or {}
                calculation_gaps = calculation_gate.get("missing_items") or []
                material_gaps = material_gate.get("missing_materials") or []
                if calculation_gate.get("status") == "blocked_by_data" and calculation_gaps:
                    gap_labels = "、".join(item.get("label", "关键指标") for item in calculation_gaps[:3])
                    add_item(
                        item_id=f"case-bonus-data-{case.id}",
                        item_type="bonus",
                        priority="high",
                        title=f"补齐奖金核算指标：{case.case_number}",
                        description=f"缺少会影响整案奖金测算的关键指标：{gap_labels}。未补齐前整案暂不测算。",
                        target_type="case",
                        target_id=case.id,
                        action="review_bonus_data",
                        created_at=case.updated_at or case.created_at,
                        meta={"missing_items": calculation_gaps},
                    )
                if material_gate.get("status") != "ready" and material_gaps:
                    add_item(
                        item_id=f"case-bonus-materials-{case.id}",
                        item_type="bonus",
                        priority="medium",
                        title=f"补齐奖金佐证材料：{case.case_number}",
                        description=f"需要补齐佐证材料：{'、'.join(material_gaps[:3])}。材料用于复核佐证，不作为计算字段本身。",
                        target_type="case",
                        target_id=case.id,
                        action="review_bonus_materials",
                        created_at=case.updated_at or case.created_at,
                        meta={"missing_materials": material_gaps},
                    )
            except Exception as exc:
                db.rollback()
                add_item(
                    item_id=f"case-bonus-error-{case.id}",
                    item_type="bonus",
                    priority="medium",
                    title=f"复核奖金核算门禁：{case.case_number}",
                    description=f"奖金门禁检查失败：{exc}",
                    target_type="case",
                    target_id=case.id,
                    action="review_bonus_data",
                    created_at=case.updated_at or case.created_at,
                )

        try:
            experience = _existing_experience_card(case)
            if experience:
                if experience.get("manual_review_status") != "confirmed":
                    add_item(
                        item_id=f"case-experience-{case.id}",
                        item_type="experience",
                        priority="medium",
                        title=f"复核经验卡：{case.case_number}",
                        description="该案件已生成经验卡，需人工确认事实、推断和建议边界后进入经验资产库。",
                        target_type="case",
                        target_id=case.id,
                        action="review_experience_card",
                        created_at=case.updated_at or case.created_at,
                        meta={"manual_review_status": experience.get("manual_review_status")},
                    )
            elif _has_experience_card_inputs(case):
                add_item(
                    item_id=f"case-experience-{case.id}",
                    item_type="experience",
                    priority="medium",
                    title=f"生成经验卡：{case.case_number}",
                    description="该案件可沉淀作案条件、发现方式、防护短板、证据缺口和可复用建议，建议进入批处理或案件研判页生成。",
                    target_type="case",
                    target_id=case.id,
                    action="generate_experience_card",
                    created_at=case.updated_at or case.created_at,
                    meta={"manual_review_status": "not_generated"},
                )
        except Exception as exc:
            db.rollback()
            add_item(
                item_id=f"case-experience-error-{case.id}",
                item_type="experience",
                priority="low",
                title=f"生成经验卡失败：{case.case_number}",
                description=f"经验卡生成遇到异常：{exc}",
                target_type="case",
                target_id=case.id,
                action="generate_experience_card",
                created_at=case.updated_at or case.created_at,
            )

    for conclusion in (
        db.query(Conclusion)
        .filter(Conclusion.status == "needs_review")
        .order_by(Conclusion.created_at.desc())
        .limit(20)
        .all()
    ):
        high_risk = conclusion.risk_level == "high"
        add_item(
            item_id=f"conclusion-review-{conclusion.id}",
            item_type="review",
            priority="high" if high_risk else "medium",
            title=f"复核研判结论 #{conclusion.id}",
            description=conclusion.summary or "该结论需要人工复核事实、推断与建议边界后再发布。",
            target_type="conclusion",
            target_id=conclusion.id,
            action="review_conclusion",
            created_at=conclusion.created_at,
        )

    for event in (
        db.query(Event)
        .filter(Event.related_case_id.is_(None))
        .order_by(Event.occurred_time.desc())
        .limit(20)
        .all()
    ):
        priority = "high" if event.risk_level in {"high", "critical"} else "medium"
        add_item(
            item_id=f"event-case-{event.id}",
            item_type="workflow",
            priority=priority,
            title=f"研判事件是否转案件：{event.event_number}",
            description=event.title or event.description or "事件尚未关联案件，可视情况转入案件流程。",
            target_type="event",
            target_id=event.id,
            action="convert_event_to_case",
            created_at=event.created_at,
        )

    for alert in (
        db.query(AutomationAlert)
        .filter(AutomationAlert.status.in_(["pending_review", "new", "open"]))
        .order_by(AutomationAlert.occurred_time.desc())
        .limit(20)
        .all()
    ):
        priority = "high" if alert.risk_level in {"high", "critical"} or alert.level == "high" else "medium"
        add_item(
            item_id=f"alert-review-{alert.id}",
            item_type="alert",
            priority=priority,
            title=f"核查数智告警研判包：{alert.alert_number}",
            description=alert.title or alert.description or "该告警需要核查原始感知、AI研判和关联案件线索。",
            target_type="alert",
            target_id=alert.id,
            action="open_alert_triage_pack",
            created_at=alert.occurred_time or alert.created_at,
            meta={
                "alert_type": alert.alert_type,
                "risk_level": alert.risk_level,
                "related_case_id": alert.related_case_id,
            },
        )

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
            add_item(
                item_id=f"meeting-conclusion-{meeting.meeting_id}",
                item_type="report_quality",
                priority="medium",
                title=f"沉淀会议报告结论：{meeting.meeting_id}",
                description="该会议已完成但尚未形成可引用结论，建议补充事实引用、分歧点和建议边界。",
                target_type="meeting",
                target_id=meeting.meeting_id,
                action="open_analysis_package",
                created_at=meeting.completed_at or meeting.created_at,
            )

    for risk in (
        db.query(AreaRiskAssessment)
        .filter(AreaRiskAssessment.risk_score >= 60)
        .order_by(AreaRiskAssessment.risk_score.desc())
        .limit(10)
        .all()
    ):
        add_item(
            item_id=f"area-reference-{risk.id}",
            item_type="workflow",
            priority="high" if risk.risk_score >= 80 else "medium",
            title=f"查看区域防控参考：{risk.area_name}",
            description=f"当前风险评分 {risk.risk_score:.0f}，建议复核区域风险依据、近期案件和防护短板，不创建执行记录。",
            target_type="area",
            target_id=risk.area_name,
            action="review_prevention_reference",
            created_at=risk.updated_at or risk.created_at,
            meta={
                "risk_score": risk.risk_score,
                "risk_level": risk.risk_level,
                "case_count_30d": risk.case_count_30d,
            },
        )

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda item: (priority_rank.get(item["priority"], 9), item["created_at"]), reverse=False)

    filtered = [item for item in suggestions if item["status"] == status] if status else suggestions
    return {
        "suggestions": filtered[:limit],
        "total": len(filtered),
        "generated_at": now.isoformat(),
    }
