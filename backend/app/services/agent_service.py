import json
import re
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.models.agent_task import AgentTask
from app.models.ai_model import AIModel
from app.ai.model_factory import ModelFactory
from app.services.case_service import CaseService
from app.services.case_intelligence_service import CaseIntelligenceService
from app.utils.logger import logger


class AgentService:
    @staticmethod
    def _get_llm(db: Session):
        model = db.query(AIModel).filter(
            AIModel.is_active == True,
            AIModel.is_default == True,
        ).first()
        if not model:
            model = db.query(AIModel).filter(AIModel.is_active == True).first()
        if not model:
            return None
        try:
            return ModelFactory().create_llm(model)
        except Exception as e:
            logger.error(f"创建Agent模型失败: {e}")
            return None

    @staticmethod
    def _parse_json_payload(content: str) -> Dict[str, Any]:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            raise

    @staticmethod
    def _trim_context_pack(pack: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "selected_case": pack.get("selected_case"),
            "facts": (pack.get("facts") or [])[:12],
            "pattern_inferences": (pack.get("pattern_inferences") or [])[:8],
            "prevention_references": (pack.get("prevention_references") or [])[:8],
            "information_gaps": (pack.get("information_gaps") or [])[:8],
            "evidence_index": (pack.get("evidence_index") or [])[:12],
            "system_boundary": pack.get("system_boundary") or [],
        }

    @staticmethod
    def _build_task_context(db: Session, case_ids: List[int]) -> List[Dict[str, Any]]:
        packs: List[Dict[str, Any]] = []
        if case_ids:
            for case_id in case_ids[:5]:
                try:
                    packs.append(CaseIntelligenceService.build_llm_context_pack(
                        db,
                        case_id=case_id,
                        days=365,
                        limit=6,
                    ))
                except Exception as exc:
                    logger.warning(f"构建案件研判上下文失败 case_id={case_id}: {exc}")
        if not packs:
            packs.append(CaseIntelligenceService.build_llm_context_pack(
                db,
                case_id=None,
                days=365,
                limit=6,
            ))
        return packs

    @staticmethod
    def _fallback_payload(query: str, context_packs: List[Dict[str, Any]]) -> Dict[str, Any]:
        trimmed = [AgentService._trim_context_pack(pack) for pack in context_packs]
        facts = [item for pack in trimmed for item in pack.get("facts", [])][:10]
        inferences = [
            item.get("claim")
            for pack in trimmed
            for item in pack.get("pattern_inferences", [])
            if item.get("claim")
        ][:8]
        recommendations = [
            item.get("action") or item.get("title")
            for pack in trimmed
            for item in pack.get("prevention_references", [])
            if item.get("action") or item.get("title")
        ][:8]
        information_gaps = [
            item
            for pack in trimmed
            for item in pack.get("information_gaps", [])
        ][:8]
        evidence_refs = [
            item.get("summary")
            for pack in trimmed
            for item in pack.get("evidence_index", [])
            if item.get("summary")
        ][:10]
        boundary = trimmed[0].get("system_boundary", []) if trimmed else []

        return {
            "steps": [
                "读取案件研判上下文包",
                "区分事实依据、模式推断和防控参考",
                "整理信息缺口与人工复核点",
                "形成可复制的研判辅助方案",
            ],
            "result": f"已围绕“{query}”生成研判辅助方案。请先核对事实依据和信息缺口，再决定是否采纳防控参考。",
            "confidence": 0.48 if facts else 0.25,
            "facts": facts,
            "inferences": inferences,
            "recommendations": recommendations,
            "information_gaps": information_gaps,
            "evidence_refs": evidence_refs,
            "boundary": boundary,
            "mode": "deterministic_fallback",
        }

    @staticmethod
    async def run_task(
        db: Session,
        query: str,
        case_ids: Optional[List[int]] = None,
    ) -> AgentTask:
        case_ids = case_ids or []
        cases = CaseService.get_cases_by_ids(db, case_ids) if case_ids else []
        case_brief = [
            {
                "case_id": c.id,
                "case_number": c.case_number,
                "description": (c.description or "")[:200],
                "case_type": c.case_type,
                "location": c.location,
            }
            for c in cases
        ]
        context_packs = AgentService._build_task_context(db, case_ids)
        compact_context = [
            AgentService._trim_context_pack(pack)
            for pack in context_packs
        ]

        llm = AgentService._get_llm(db)
        if llm:
            prompt = f"""你是涉油案件研判辅助 Agent。请只基于系统给出的案件研判上下文输出 JSON，不要编造未掌握事实。
必须遵守：
1. 区分 facts、inferences、recommendations、information_gaps；
2. recommendations 只能是防控参考或信息补齐建议，不能写成已执行任务；
3. 不做犯罪预测，不自动创建外勤任务，不编造未掌握的人车链条或销赃链条；
4. confidence 为 0-1，依据不足时降低置信度。

JSON字段：
steps(字符串数组)，result(字符串)，confidence(0-1)，facts(字符串数组)，inferences(字符串数组)，recommendations(字符串数组)，information_gaps(字符串数组)，evidence_refs(字符串数组)，boundary(字符串数组)。
用户目标：{query}
相关案件：{json.dumps(case_brief, ensure_ascii=False)}
研判上下文：{json.dumps(compact_context, ensure_ascii=False, default=str)}
"""
            try:
                response = await llm.ainvoke(prompt)
                content = response.content if hasattr(response, "content") else str(response)
                payload = AgentService._parse_json_payload(content)
            except Exception as e:
                logger.warning(f"Agent结果解析失败，使用降级方案: {e}")
                payload = AgentService._fallback_payload(query, context_packs)
        else:
            payload = AgentService._fallback_payload(query, context_packs)

        task = AgentTask(
            query=query,
            case_ids=case_ids,
            status="completed",
            result=payload,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task
