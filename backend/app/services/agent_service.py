"""Legacy model selection helper retained for well-attention compatibility.

The old single-turn task executor is retired. New queries use intelligent_queries.
"""
from sqlalchemy.orm import Session

from app.models.ai_model import AIModel
from app.ai.model_factory import ModelFactory
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
