from abc import ABC, abstractmethod
from langchain.chat_models.base import BaseChatModel
from app.models.ai_model import AIModel

class BaseAgent(ABC):
    """基础智能体类"""
    
    def __init__(self, model: AIModel, llm: BaseChatModel):
        self.model = model
        self.llm = llm
        self.name = model.name
        self.model_id = model.id
    
    @abstractmethod
    async def process(self, input_data: dict) -> dict:
        """处理输入并返回结果"""
        pass

