from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.config import settings
from app.models.case import Case
from app.services.case_automation_service import CaseAutomationService
from app.services.case_profile_service import CaseProfileService


class CaseProcessingCardService:
    """把单案质量、奖金、经验卡、报告/结论缺口归并成一张人工处理卡。"""

    @staticmethod
    def build_processing_card(db: Session, case_id: int) -> Dict[str, Any]:
        case = CaseProfileService.get_case(db, case_id)
        profile = CaseProfileService.build_case_profile(db, case_id, include_similar=False)
        gap_groups = CaseProcessingCardService._gap_groups(db, case, profile)
        priority = CaseProcessingCardService._priority(gap_groups)
        actions = CaseProcessingCardService._actions(case, gap_groups)
        return {
            "case_id": case.id,
            "case_number": case.case_number,
            "status": "needs_review" if gap_groups else "ready",
            "priority": priority,
            "gap_groups": gap_groups,
            "impacted_modules": sorted({module for group in gap_groups for module in group.get("impacted_modules", [])}),
            "suggested_actions": actions,
            "manual_review_required": bool(gap_groups),
            "profile_snapshot": {
                "quality_score": profile.get("quality", {}).get("score") or profile.get("quality", {}).get("quality_score"),
                "has_evidence": profile.get("availability", {}).get("has_evidence"),
                "has_confirmed_experience": profile.get("availability", {}).get("has_confirmed_experience"),
            },
            "boundary": "处理卡只归并缺口和复核入口，不自动派发任务，不自动发布结论。",
        }

    @staticmethod
    def _gap_groups(db: Session, case: Case, profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        groups: List[Dict[str, Any]] = []
        quality_gaps = profile.get("quality_gaps") or []
        if quality_gaps:
            groups.append({
                "key": "quality",
                "label": "案件质量缺口",
                "severity": "high",
                "items": quality_gaps[:8],
                "impacted_modules": ["案件画像", "相似案件", "研判报告"],
                "route": f"/cases?caseId={case.id}",
            })

        bonus_group = CaseProcessingCardService._bonus_group(db, case)
        if bonus_group:
            groups.append(bonus_group)

        experience = profile.get("experience_card") or {}
        if experience.get("manual_review_status") not in {"confirmed", "approved"}:
            groups.append({
                "key": "experience",
                "label": "经验卡待确认",
                "severity": "medium",
                "items": [
                    {
                        "field": "manual_review_status",
                        "label": "经验卡未确认",
                        "reason": "只有已确认经验卡才能进入知识资产库和相似召回。",
                    }
                ],
                "impacted_modules": ["经验卡资产库", "研判搜索"],
                "route": f"/case-intelligence?caseId={case.id}",
            })

        conclusions = profile.get("knowledge_refs", {}).get("conclusions") or []
        if any(item.get("status") in {"draft", "needs_review", "flagged"} for item in conclusions):
            groups.append({
                "key": "report",
                "label": "报告/结论复核缺口",
                "severity": "medium",
                "items": [
                    {
                        "field": "conclusion_review",
                        "label": "结论待人工复核",
                        "reason": "结论草稿或风险结论发布前需要核对事实引用。",
                    }
                ],
                "impacted_modules": ["分析报告", "情报结论", "待办中心"],
                "route": f"/conclusions?caseId={case.id}",
            })
        return groups

    @staticmethod
    def _bonus_group(db: Session, case: Case) -> Dict[str, Any] | None:
        if not settings.ENABLE_BONUS_ACCOUNTING:
            return None
        try:
            bonus = CaseAutomationService.build_bonus_assessment(db, case)
        except Exception:
            return {
                "key": "bonus",
                "label": "奖金核算待复核",
                "severity": "medium",
                "items": [{"field": "bonus", "label": "奖金核算数据需人工复核", "reason": "系统暂不能完成规则测算。"}],
                "impacted_modules": ["奖金核算"],
                "route": f"/cases/bonus?caseId={case.id}",
            }
        missing = [
            {"field": "material", "label": item, "reason": "奖金核算材料门禁要求"}
            for item in bonus.get("material_gate", {}).get("missing_materials", [])
        ]
        missing.extend(
            {"field": item.get("key") or "bonus_data", "label": item.get("label") or str(item), "reason": "奖金核算指标缺口"}
            for item in bonus.get("calculation_gate", {}).get("missing_items", [])
            if isinstance(item, dict)
        )
        if not missing and bonus.get("ready_for_review"):
            return None
        return {
            "key": "bonus",
            "label": "奖金核算缺口",
            "severity": "medium",
            "items": missing[:8] or [{"field": "bonus_review", "label": "奖金测算需人工复核", "reason": "奖金发放前必须人工确认。"}],
            "impacted_modules": ["奖金核算", "案件处理卡"],
            "route": f"/cases/bonus?caseId={case.id}",
        }

    @staticmethod
    def _priority(groups: List[Dict[str, Any]]) -> str:
        severities = {item.get("severity") for item in groups}
        if "high" in severities:
            return "high"
        if "medium" in severities:
            return "medium"
        return "low"

    @staticmethod
    def _actions(case: Case, groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "key": f"review_{group['key']}",
                "label": f"复核{group['label']}",
                "route": group.get("route") or f"/cases?caseId={case.id}",
                "mutation_allowed": False,
                "reason": "AI 和规则结果只提供复核入口，写入需人工确认。",
            }
            for group in groups
        ]
