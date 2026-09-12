import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.automation_alert import AutomationAlert
from app.models.case import Case
from app.models.conclusion import Conclusion
from app.models.event import Event
from app.models.meeting import Meeting
from app.models.patrol import AreaRiskAssessment
from app.models.report import Report
from app.services.case_automation_service import CaseAutomationService
from app.services.case_processing_card_service import CaseProcessingCardService
from app.services.case_profile_service import CaseProfileService
from app.services.case_quality_service import CaseQualityService
from app.services.case_result_access import CaseResultAccessError
from app.services.conclusion_factory_service import ConclusionFactoryService

router = APIRouter()
logger = logging.getLogger(__name__)


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


SuggestionWorkflow = Literal[
    "all", "coordinate_gap", "data_quality", "processing_card", "bonus_metric_gap",
    "bonus_material_gap", "alert", "conclusion_review", "report_followup", "experience",
    "event_review", "area_reference",
]


def _workflow(item_id: str, item_type: str, action: str) -> str:
    if item_id.startswith("case-geo-"):
        return "coordinate_gap"
    return {
        "review_processing_card": "processing_card",
        "review_bonus_data": "bonus_metric_gap",
        "review_bonus_materials": "bonus_material_gap",
        "review_conclusion": "conclusion_review",
        "review_experience_card": "experience",
        "open_analysis_package": "report_followup",
        "convert_event_to_case": "event_review",
        "open_alert_triage_pack": "alert",
        "review_prevention_reference": "area_reference",
    }.get(action, item_type if item_type in {"experience", "data_quality"} else "data_quality")


def _derive_bonus_data_gaps_from_items(bonus_items) -> list[dict]:
    gaps = []
    for item in bonus_items or []:
        if not isinstance(item, dict) or item.get("status") != "blocked_by_data":
            continue
        blocked_by = item.get("blocked_by") or []
        if not blocked_by:
            continue
        gaps.append({
            "key": item.get("key"),
            "label": item.get("label") or item.get("key") or "关键指标",
            "blocked_by": blocked_by,
        })
    return gaps


def _bonus_calculation_gaps(bonus: dict) -> list:
    calculation_gate = bonus.get("calculation_gate") if isinstance(bonus.get("calculation_gate"), dict) else {}
    missing_items = calculation_gate.get("missing_items") or []
    if missing_items:
        return missing_items
    return _derive_bonus_data_gaps_from_items(bonus.get("bonus_items"))


@router.get("/")
def get_suggestions(
    limit: int = Query(50, ge=1, le=200),
    status: str = "open",
    offset: int = Query(0, ge=0),
    workflow: SuggestionWorkflow = "all",
    db: Session = Depends(get_db),
):
    """只收纳真实缺项及已有成果待判断项，先鉴权和统计，再筛选与分页。"""
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
            "workflow": _workflow(item_id, item_type, action),
            "status": "open",
            "created_at": _iso(created_at, now),
            "meta": meta or {},
        })

    for case in (
        db.query(Case)
        .filter(Case.status.in_(["pending", "processing"]))
        .order_by(Case.created_at.desc(), Case.id.desc())
        .all()
    ):
        try:
            processing_card = CaseProcessingCardService.build_processing_card(db, case.id)
            gap_groups = processing_card.get("gap_groups") or []
            if gap_groups:
                add_item(
                    item_id=f"case-processing-card-{case.id}",
                    item_type="processing_card",
                    priority=processing_card.get("priority") or "medium",
                    title=f"处理案件缺口卡：{case.case_number}",
                    description="已归并真实资料缺项及已有成果待判断事项；不要求每案生成经验卡或报告。",
                    target_type="case",
                    target_id=case.id,
                    action="review_processing_card",
                    created_at=case.updated_at or case.created_at,
                    meta={
                        "status": processing_card.get("status"),
                        "gap_group_count": len(gap_groups),
                        "gap_labels": [group.get("label") for group in gap_groups if group.get("label")],
                        "impacted_modules": processing_card.get("impacted_modules") or [],
                    },
                )
        except Exception:
            db.rollback()
            logger.exception("Failed to build processing card suggestion for case %s", case.id)

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
        quality = case.quality_issues or CaseQualityService.evaluate_case(db, case)
        quality_score = quality.get("score")
        if quality.get("level") == "low" or (quality_score is not None and quality_score < 70):
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
                calculation_gate = bonus.get("calculation_gate") if isinstance(bonus.get("calculation_gate"), dict) else {}
                material_gate = bonus.get("material_gate") or {}
                calculation_gaps = _bonus_calculation_gaps(bonus)
                material_gaps = material_gate.get("missing_materials") or []
                calculation_blocked = calculation_gate.get("status") == "blocked_by_data" or bool(calculation_gaps)
                if calculation_blocked and calculation_gaps:
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
            except Exception:
                db.rollback()
                logger.exception("Failed to build bonus assessment for case %s", case.id)
                add_item(
                    item_id=f"case-bonus-error-{case.id}",
                    item_type="bonus",
                    priority="medium",
                    title=f"复核奖金核算门禁：{case.case_number}",
                    description="奖金门禁检查遇到异常，请进入案件页人工复核指标和材料。",
                    target_type="case",
                    target_id=case.id,
                    action="review_bonus_data",
                    created_at=case.updated_at or case.created_at,
                )

        try:
            experience = _existing_experience_card(case)
            if CaseProfileService.experience_needs_review(experience):
                add_item(
                    item_id=f"case-experience-{case.id}",
                    item_type="experience",
                    priority="medium",
                    title=f"复核已有经验卡：{case.case_number}",
                    description="已有经验卡草稿可按需确认或归档；未经确认不能作为已核验经验复用。",
                    target_type="case",
                    target_id=case.id,
                    action="review_experience_card",
                    created_at=case.updated_at or case.created_at,
                    meta={"manual_review_status": experience.get("manual_review_status")},
                )
        except Exception:
            db.rollback()
            logger.exception("Failed to inspect experience card for case %s", case.id)
            add_item(
                item_id=f"case-experience-error-{case.id}",
                item_type="experience",
                priority="low",
                title=f"经验卡状态暂不可用：{case.case_number}",
                description="现有经验卡状态暂时无法读取，请稍后重试；无需重新生成。",
                target_type="case",
                target_id=case.id,
                action="review_experience_card",
                created_at=case.updated_at or case.created_at,
            )

    for conclusion in (
        db.query(Conclusion)
        .filter(Conclusion.status.in_(["draft", "needs_review", "flagged"]))
        .order_by(Conclusion.created_at.desc(), Conclusion.id.desc())
        .yield_per(100)
    ):
        try:
            ConclusionFactoryService.require_conclusion_result_access(db, conclusion)
        except CaseResultAccessError:
            continue
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
        .order_by(Event.occurred_time.desc(), Event.id.desc())
        .yield_per(100)
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
        .order_by(AutomationAlert.occurred_time.desc(), AutomationAlert.id.desc())
        .yield_per(100)
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
        .filter(db.query(Report.id).filter(Report.meeting_id == Meeting.meeting_id).exists())
        .order_by(Meeting.completed_at.desc(), Meeting.meeting_id.desc())
        .yield_per(100)
    ):
        has_conclusion = False
        for item in db.query(Conclusion).filter(Conclusion.meeting_id == meeting.meeting_id):
            try:
                ConclusionFactoryService.require_conclusion_result_access(db, item)
            except CaseResultAccessError:
                continue
            has_conclusion = True
            break
        if not has_conclusion:
            add_item(
                item_id=f"meeting-conclusion-{meeting.meeting_id}",
                item_type="report_quality",
                priority="medium",
                title=f"查看已有会议报告：{meeting.meeting_id}",
                description="会议报告已经形成，可核对事实引用、分歧点和建议边界；不要求再生成单独结论。",
                target_type="meeting",
                target_id=meeting.meeting_id,
                action="open_analysis_package",
                created_at=meeting.completed_at or meeting.created_at,
            )

    # 旧区域评分没有授权辖区字段，不能把全域记录交给仅有部分辖区权限的用户。
    risk_query = (
        db.query(AreaRiskAssessment)
        .filter(AreaRiskAssessment.risk_score >= 60)
        .order_by(AreaRiskAssessment.risk_score.desc(), AreaRiskAssessment.id.desc())
    )
    for risk in risk_query.yield_per(100) if db.info.get("authorized_area_ids") is None else []:
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
    suggestions.sort(key=lambda item: (priority_rank.get(item["priority"], 9), item["created_at"], item["id"]))

    filtered = [item for item in suggestions if item["status"] == status] if status else suggestions
    priorities = Counter(item["priority"] for item in filtered)
    summary = {
        "total": len(filtered),
        "priority": {name: priorities[name] for name in ("high", "medium", "low")},
        "type": dict(Counter(item["type"] for item in filtered)),
        "workflow": dict(Counter(item["workflow"] for item in filtered)),
    }
    if workflow != "all":
        filtered = [item for item in filtered if item["workflow"] == workflow]
    return {
        "suggestions": filtered[offset:offset + limit],
        "total": len(filtered),
        "summary": summary,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < len(filtered),
        "generated_at": now.isoformat(),
    }
