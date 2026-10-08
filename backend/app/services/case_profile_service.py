from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.automation_alert import AutomationAlert
from app.models.case import Case, CaseEvidence, CasePerson, CaseTip, CaseVehicle, OilRecoveryRecord
from app.models.conclusion import Conclusion
from app.models.meeting import Meeting
from app.models.report import Report
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.case_result_access import CaseResultAccessError
from app.services.case_saved_profile import read_saved_profile
from app.services.experience_state_service import read_experience_state


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else ([] if value is None else [value])


class CaseProfileService:
    """统一案件画像底座。

    该服务只聚合已存在的数据，不调用会提交事务的生成路径，确保 GET 读取不改库。
    """

    @staticmethod
    def get_case(db: Session, case_id: int) -> Case:
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError("case_not_found")
        return case

    @staticmethod
    def experience_needs_review(experience_card: Dict[str, Any]) -> bool:
        """仅已有待判断草稿需要复核；未创建、已确认或归档的经验不构成缺项。"""
        return bool(experience_card) and experience_card.get("manual_review_status") in {
            None, "draft", "pending", "needs_review", "flagged",
        }

    @staticmethod
    def build_case_profile(db: Session, case_id: int, include_similar: bool = True,
                           *, saved_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        case = CaseProfileService.get_case(db, case_id)
        related = CaseProfileService._related(db, case.id)
        saved = saved_profile if saved_profile is not None else read_saved_profile(db, case)
        payload = _as_dict((saved.get("data") or {}).get("payload")) if saved["status"] == "ready" else {}
        quality = payload.get("quality") or case.quality_issues
        if quality:
            from app.services.case_quality_service import QUALITY_RULE_VERSION
            if quality.get("rule_version") != QUALITY_RULE_VERSION:
                # GET reuses saved results. An old rule's prompts are history,
                # not current requirements; only the background pipeline may
                # replace them with a newly evaluated result.
                quality = {
                    "state": "stale",
                    "rule_version": quality.get("rule_version"),
                    "score": quality.get("score"),
                    "level": quality.get("level"),
                    "score_purpose": "historical_reference_only",
                    "missing_required": [],
                    "priority_gaps": [],
                    "historical_result": quality,
                    "reason": "历史规则结果仅供查看，不作为当前缺项或待办；读取不重新分析。",
                }
        else:
            quality = {"missing_required": [], "state": "not_generated"}
        features = _as_dict(case.features)
        experience_state = read_experience_state(db, case)
        experience_card = experience_state["card"] or {}
        tags = []
        similar = {"case_id": case.id, "items": [], "state": "not_requested",
                   "reason": "历史参考由独立统一检索入口提供，画像读取不重复搜索。"}
        reports = CaseProfileService._reports(db, case)
        conclusions = CaseProfileService._conclusions(db, case.id)
        alerts = CaseProfileService._alerts(db, case.id)

        return {
            "case": CaseProfileService._case_brief(case),
            "facts": CaseProfileService._facts(case, related),
            "related": related,
            "quality": quality,
            "quality_gaps": quality.get("priority_gaps", quality.get("missing_required", [])[:3]) if isinstance(quality, dict) else [],
            "standard_profile": saved,
            "ai_summary": {
                "summary": case.description,
                "source": "original_record",
                "state": saved["status"],
                "preprocess_mode": "saved_standard_profile",
                "analysis_readiness": payload.get("analysis_readiness") or {},
                "features": payload,
                "legacy_summary": {"state": "historical_unversioned", "text": features.get("summary") or features.get("case_summary")},
            },
            "tags": tags,
            "similar_cases": similar,
            "experience_card": experience_card or None,
            "experience_state": experience_state,
            "knowledge_refs": {
                "reports": reports,
                "conclusions": conclusions,
                "alerts": alerts,
            },
            "availability": {
                "has_geo": case.latitude is not None and case.longitude is not None,
                "has_evidence": bool(related["evidence"]),
                "has_ai_features": saved["status"] == "ready",
                "has_quality": bool(case.quality_issues),
                "has_confirmed_experience": experience_state["confirmed"],
                "needs_human_review": bool(quality.get("missing_required") if isinstance(quality, dict) else True)
                or experience_state["needs_review"]
                or any(item.get("status") == "flagged" for item in conclusions),
            },
            "source_map": {
                "case": f"case:{case.id}",
                "quality": f"case:{case.id}:quality",
                "features": f"case:{case.id}:features",
                "experience_card": (f"knowledge_asset:{experience_state['asset_id']}:v{experience_state['asset_version']}"
                                    if experience_state.get("asset_id") else
                                    f"case:{case.id}:legacy_experience_card" if experience_card else None),
                "evidence": [f"case_evidence:{item['id']}" for item in related["evidence"] if item.get("id")],
                "conclusions": [f"conclusion:{item['id']}" for item in conclusions],
                "alerts": [f"automation_alert:{item['id']}" for item in alerts],
            },
            "boundary": [
                "案件画像只整合已录入事实、规则分析结果和人工确认状态。",
                "读取画像不生成经验卡、不刷新质量评分、不提交数据库事务。",
                "AI 内容均为候选或辅助研判，不替代人工确认。",
            ],
        }

    @staticmethod
    def _case_brief(case: Case) -> Dict[str, Any]:
        return {
            "id": case.id,
            "case_number": case.case_number,
            "occurred_time": _iso(case.occurred_time),
            "occurred_from": _iso(getattr(case, "occurred_from", None)),
            "occurred_to": _iso(getattr(case, "occurred_to", None)),
            "time_precision": getattr(case, "time_precision", None) or "unknown",
            "time_expression": getattr(case, "time_expression", None),
            "time_timezone": getattr(case, "time_timezone", None),
            "discovered_at": _iso(getattr(case, "discovered_at", None)),
            "location": case.location,
            "latitude": case.latitude,
            "longitude": case.longitude,
            "case_type": case.case_type,
            "description": case.description,
            "status": case.status,
            "report_unit": case.report_unit,
            "source_type": case.source_type,
            "current_stage": case.current_stage,
            "oil_type": case.oil_type,
            "oil_volume": case.oil_volume,
            "oil_volume_unit": getattr(case, "oil_volume_unit", None) or "unknown",
            "oil_value": case.oil_value,
            "oil_nature": case.oil_nature,
            "facility_type": case.facility_type,
            "facility_owner": case.facility_owner,
            "modus_operandi": case.modus_operandi,
        }

    @staticmethod
    def _facts(case: Case, related: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        return {
            "time": _iso(case.occurred_time),
            "time_precision": getattr(case, "time_precision", None) or "unknown",
            "occurred_from": _iso(getattr(case, "occurred_from", None)),
            "occurred_to": _iso(getattr(case, "occurred_to", None)),
            "location": case.location,
            "source_type": case.source_type,
            "oil": {
                "oil_type": case.oil_type,
                "oil_volume": case.oil_volume,
                "oil_volume_unit": getattr(case, "oil_volume_unit", None) or "unknown",
                "oil_nature": case.oil_nature,
                "oil_handling": case.oil_handling,
                "recovery_count": len(related["oil_recovery"]),
            },
            "actors": {
                "vehicle_count": len(related["vehicles"]),
                "person_count": len(related["persons"]),
            },
            "evidence_count": len(related["evidence"]),
            "tip_count": len(related["tips"]),
        }

    @staticmethod
    def _related(db: Session, case_id: int) -> Dict[str, List[Dict[str, Any]]]:
        vehicles = db.query(CaseVehicle).filter(CaseVehicle.case_id == case_id).all()
        persons = db.query(CasePerson).filter(CasePerson.case_id == case_id).all()
        evidence = db.query(CaseEvidence).filter(CaseEvidence.case_id == case_id).all()
        oil_recovery = db.query(OilRecoveryRecord).filter(OilRecoveryRecord.case_id == case_id).all()
        tips = db.query(CaseTip).filter(CaseTip.case_id == case_id).all()
        return {
            "vehicles": [
                {
                    "id": item.id,
                    "vehicle_type": item.vehicle_type,
                    "plate_number": item.plate_number,
                    "handling_status": item.handling_status,
                    "custody_location": item.custody_location,
                    "current_location": item.current_location,
                    "transferred_to_police": item.transferred_to_police,
                }
                for item in vehicles
            ],
            "persons": [
                {
                    "id": item.id,
                    "name": item.name,
                    "role": item.role,
                    "handling_status": item.handling_status,
                }
                for item in persons
            ],
            "evidence": [
                {
                    "id": item.id,
                    "evidence_type": item.evidence_type,
                    "title": item.title,
                    "requirement_key": item.requirement_key,
                    "captured_at": _iso(item.captured_at),
                    "file_path": item.file_path,
                    "notes": item.notes,
                }
                for item in evidence
            ],
            "oil_recovery": [
                {
                    "id": item.id,
                    "oil_nature": item.oil_nature,
                    "volume_tons": item.volume_tons,
                    "water_cut": item.water_cut,
                    "source": item.source,
                    "receiver": item.receiver,
                    "handled_at": _iso(item.handled_at),
                    "handling_method": item.handling_method,
                }
                for item in oil_recovery
            ],
            "tips": [
                {
                    "id": item.id,
                    "reported_at": _iso(item.reported_at),
                    "location": item.location,
                    "content": item.content,
                    "source_type": item.source_type,
                    "verification_status": item.verification_status,
                }
                for item in tips
            ],
        }

    @staticmethod
    def _safe_tags(db: Session, case: Case) -> List[Dict[str, Any]]:
        try:
            return CaseIntelligenceService.build_case_tags(db, case).get("tags", [])
        except Exception:
            return []

    @staticmethod
    def _safe_similar_cases(db: Session, case_id: int) -> Dict[str, Any]:
        from sqlalchemy.exc import SQLAlchemyError

        try:
            return CaseIntelligenceService.find_similar_cases(db, case_id, days=365, limit=5)
        except SQLAlchemyError:
            # A failed PostgreSQL statement may abort the caller's transaction.
            # Do not continue aggregating reads or rollback unrelated work here.
            raise
        except Exception:
            return {"case_id": case_id, "items": [], "state": "unavailable",
                    "coverage": {"complete": False, "recency_limit": None},
                    "boundary": "历史参考暂不可用，不能据此判断没有相似案件。"}

    @staticmethod
    def _conclusions(db: Session, case_id: int) -> List[Dict[str, Any]]:
        # 历史记录只读鉴权，不再依赖或恢复旧结论生成器。
        from app.services.legacy_conclusion_access import require_conclusion_result_access

        items = []
        for item in db.query(Conclusion).filter(Conclusion.case_id == case_id).order_by(Conclusion.id.desc()).limit(8):
            try:
                require_conclusion_result_access(db, item)
            except CaseResultAccessError:
                # 不返回标题、状态、编号或隐藏数量；处理卡和source_map也只基于可读结果。
                continue
            evidence = _as_dict(item.evidence)
            items.append({
                "id": item.id,
                "status": item.status,
                "risk_level": item.risk_level,
                "summary": item.summary,
                "confidence": None if evidence.get("confidence_available") is False else item.confidence,
                "confidence_available": evidence.get("confidence_available", item.confidence is not None),
                "created_at": _iso(item.created_at),
            })
        return items

    @staticmethod
    def _alerts(db: Session, case_id: int) -> List[Dict[str, Any]]:
        return [
            {
                "id": item.id,
                "alert_number": item.alert_number,
                "title": item.title,
                "level": item.level,
                "risk_level": item.risk_level,
                "status": item.status,
                "occurred_time": _iso(item.occurred_time),
            }
            for item in db.query(AutomationAlert).filter(AutomationAlert.related_case_id == case_id).order_by(AutomationAlert.id.desc()).limit(8).all()
        ]

    @staticmethod
    def _reports(db: Session, case: Case) -> List[Dict[str, Any]]:
        from app.services.meeting_frozen_service import report_sources_visible
        meetings = db.query(Meeting).all()
        meeting_ids = [
            item.meeting_id
            for item in meetings
            if case.id in _as_list(item.case_ids)
        ]
        query = db.query(Report)
        if meeting_ids:
            query = query.filter(Report.meeting_id.in_(meeting_ids))
        else:
            query = query.filter(Report.meeting_id == "__none__")
        return [
            {
                "id": item.id,
                "meeting_id": item.meeting_id,
                "report_type": item.report_type,
                "summary": _as_dict(item.content).get("summary"),
                "created_at": _iso(item.created_at),
            }
            for item in query.order_by(Report.id.desc()).limit(8).all()
            if report_sources_visible(db, item)
        ]
