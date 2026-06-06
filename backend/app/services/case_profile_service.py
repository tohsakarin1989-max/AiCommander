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
from app.services.case_quality_service import CaseQualityService


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
    def build_case_profile(db: Session, case_id: int, include_similar: bool = True) -> Dict[str, Any]:
        case = CaseProfileService.get_case(db, case_id)
        related = CaseProfileService._related(db, case.id)
        quality = case.quality_issues or CaseQualityService.evaluate_case(db, case)
        features = _as_dict(case.features)
        intelligence = _as_dict(features.get("intelligence"))
        experience_card = _as_dict(intelligence.get("experience_card"))
        tags = CaseProfileService._safe_tags(db, case)
        similar = (
            CaseProfileService._safe_similar_cases(db, case.id)
            if include_similar
            else {"case_id": case.id, "items": []}
        )
        reports = CaseProfileService._reports(db, case)
        conclusions = CaseProfileService._conclusions(db, case.id)
        alerts = CaseProfileService._alerts(db, case.id)

        return {
            "case": CaseProfileService._case_brief(case),
            "facts": CaseProfileService._facts(case, related),
            "related": related,
            "quality": quality,
            "quality_gaps": quality.get("missing_required", []) if isinstance(quality, dict) else [],
            "ai_summary": {
                "summary": features.get("summary") or features.get("case_summary") or case.description,
                "preprocess_mode": features.get("preprocess_mode"),
                "analysis_readiness": features.get("analysis_readiness") or {},
                "features": features,
            },
            "tags": tags,
            "similar_cases": similar,
            "experience_card": experience_card or None,
            "knowledge_refs": {
                "reports": reports,
                "conclusions": conclusions,
                "alerts": alerts,
            },
            "availability": {
                "has_geo": case.latitude is not None and case.longitude is not None,
                "has_evidence": bool(related["evidence"]),
                "has_ai_features": bool(features),
                "has_quality": bool(case.quality_issues),
                "has_confirmed_experience": experience_card.get("manual_review_status") == "confirmed",
                "needs_human_review": bool(quality.get("missing_required") if isinstance(quality, dict) else True)
                or experience_card.get("manual_review_status") not in {"confirmed", "approved"},
            },
            "source_map": {
                "case": f"case:{case.id}",
                "quality": f"case:{case.id}:quality",
                "features": f"case:{case.id}:features",
                "experience_card": f"case:{case.id}:experience_card" if experience_card else None,
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
            "location": case.location,
            "source_type": case.source_type,
            "oil": {
                "oil_type": case.oil_type,
                "oil_volume": case.oil_volume,
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
        try:
            return CaseIntelligenceService.find_similar_cases(db, case_id, days=365, limit=5)
        except Exception:
            return {"case_id": case_id, "items": []}

    @staticmethod
    def _conclusions(db: Session, case_id: int) -> List[Dict[str, Any]]:
        return [
            {
                "id": item.id,
                "status": item.status,
                "risk_level": item.risk_level,
                "summary": item.summary,
                "confidence": item.confidence,
                "created_at": _iso(item.created_at),
            }
            for item in db.query(Conclusion).filter(Conclusion.case_id == case_id).order_by(Conclusion.id.desc()).limit(8).all()
        ]

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
        ]
