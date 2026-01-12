import json
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from app.models.conclusion import Conclusion
from app.models.ai_model import AIModel
from app.ai.model_factory import ModelFactory
from app.services.case_service import CaseService
from app.services.vector_db_service import VectorDBService
from app.models.meeting import Meeting
from app.models.report import Report
from app.utils.logger import logger
from app.config import settings


class ConclusionFactoryService:
    @staticmethod
    def _get_llm(db: Session):
        model = db.query(AIModel).filter(
            AIModel.role == "moderator",
            AIModel.is_default == True,
            AIModel.is_active == True,
        ).first()
        if not model:
            model = db.query(AIModel).filter(
                AIModel.is_active == True,
            ).first()
        if not model:
            return None
        try:
            return ModelFactory().create_llm(model)
        except Exception as e:
            logger.error(f"创建结论LLM失败: {e}")
            return None

    @staticmethod
    def _build_evidence(db: Session, case_dict: Dict[str, Any]) -> Dict[str, Any]:
        evidence = {
            "case": case_dict,
            "similar_cases": [],
            "related_reports": [],
            "related_meetings": [],
        }
        if settings.ENABLE_VECTOR_DB and case_dict.get("description"):
            try:
                vector_db = VectorDBService()
                if vector_db.is_available():
                    results = vector_db.search_similar_cases(
                        case_dict.get("description", ""),
                        top_k=5,
                        min_similarity=0.6,
                    )
                    evidence["similar_cases"] = results
            except Exception as e:
                logger.warning(f"生成相似案件证据失败: {e}")

        case_id = case_dict.get("case_id")
        if case_id is not None:
            try:
                meetings = db.query(Meeting).all()
                for meeting in meetings:
                    case_ids = meeting.case_ids if isinstance(meeting.case_ids, list) else []
                    if case_id in case_ids:
                        evidence["related_meetings"].append({
                            "meeting_id": meeting.meeting_id,
                            "status": meeting.status,
                            "created_at": str(meeting.created_at) if meeting.created_at else None,
                        })
                        report = (
                            db.query(Report)
                            .filter(Report.meeting_id == meeting.meeting_id)
                            .first()
                        )
                        if report:
                            evidence["related_reports"].append({
                                "report_id": report.id,
                                "meeting_id": report.meeting_id,
                                "report_type": report.report_type,
                                "created_at": str(report.created_at) if report.created_at else None,
                            })
            except Exception as e:
                logger.warning(f"生成相关会议/报告证据失败: {e}")
        return evidence

    @staticmethod
    def _fallback_summary(case_dict: Dict[str, Any]) -> Dict[str, Any]:
        desc = case_dict.get("description") or ""
        summary = desc[:300] if desc else "暂无案件描述，建议补充案情信息。"
        confidence = 0.4 if desc else 0.2
        risk_level = "medium" if case_dict.get("loss_amount") else "unknown"
        return {
            "summary": summary,
            "confidence": confidence,
            "risk_level": risk_level,
            "key_evidence": ["案件基础信息", "结构化字段缺失提示"],
        }

    @staticmethod
    async def generate_conclusion(db: Session, case_id: int) -> Conclusion:
        case = CaseService.get_case(db, case_id)
        if not case:
            raise ValueError("案件不存在")

        case_dict = {
            "case_id": case.id,
            "case_number": case.case_number,
            "occurred_time": str(case.occurred_time),
            "location": case.location,
            "case_type": case.case_type,
            "description": case.description,
            "loss_amount": case.loss_amount,
            "modus_operandi": case.modus_operandi,
            "features": case.features,
        }
        evidence = ConclusionFactoryService._build_evidence(db, case_dict)

        llm = ConclusionFactoryService._get_llm(db)
        payload: Dict[str, Any]
        if llm:
            prompt = f"""你是资深案件分析助手，请基于案件与证据链输出结论。
要求输出JSON，字段：summary, confidence(0-1), risk_level(low|medium|high), key_evidence(字符串数组)。
案件：{json.dumps(case_dict, ensure_ascii=False)}
证据链：{json.dumps(evidence, ensure_ascii=False)}
"""
            try:
                response = await llm.ainvoke(prompt)
                content = response.content if hasattr(response, "content") else str(response)
                payload = json.loads(content)
            except Exception as e:
                logger.warning(f"结论生成解析失败，使用降级方案: {e}")
                payload = ConclusionFactoryService._fallback_summary(case_dict)
        else:
            payload = ConclusionFactoryService._fallback_summary(case_dict)

        confidence = float(payload.get("confidence", 0.0))
        risk_level = payload.get("risk_level", "unknown")
        status = "published" if confidence >= 0.7 and risk_level != "high" else "needs_review"

        conclusion = Conclusion(
            case_id=case_id,
            status=status,
            confidence=confidence,
            risk_level=risk_level,
            summary=payload.get("summary"),
            evidence={
                "key_evidence": payload.get("key_evidence", []),
                "raw": evidence,
            },
        )
        db.add(conclusion)
        db.commit()
        db.refresh(conclusion)
        return conclusion
