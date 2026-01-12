import json
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.models.agent_task import AgentTask
from app.models.ai_model import AIModel
from app.ai.model_factory import ModelFactory
from app.services.case_service import CaseService
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

        llm = AgentService._get_llm(db)
        if llm:
            prompt = f"""你是案件侦查Agent，请输出JSON字段：
steps(字符串数组)，result(字符串)，confidence(0-1)。
用户目标：{query}
相关案件：{json.dumps(case_brief, ensure_ascii=False)}
"""
            try:
                response = await llm.ainvoke(prompt)
                content = response.content if hasattr(response, "content") else str(response)
                payload = json.loads(content)
            except Exception as e:
                logger.warning(f"Agent结果解析失败，使用降级方案: {e}")
                payload = {
                    "steps": ["收集相关案件", "进行相似性与地理分析", "生成结论与证据链"],
                    "result": "暂无法生成高质量结论，请稍后重试。",
                    "confidence": 0.3,
                }
        else:
            payload = {
                "steps": ["收集相关案件", "进行相似性与地理分析", "生成结论与证据链"],
                "result": "未配置AI模型，无法执行自动侦查。",
                "confidence": 0.0,
            }

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
