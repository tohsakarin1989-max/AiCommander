from app.models.ai_model import AIModel
from app.ai.llm_providers import LLMProvider
from langchain.chat_models.base import BaseChatModel
from app.utils.logger import logger


class ModelFactory:
    """AI模型工厂，根据配置创建LLM实例"""

    def create_llm(self, model: AIModel) -> BaseChatModel:
        """
        根据模型配置创建LLM实例（通用协议）：
        - provider 支持（大小写不敏感）：
          - "openai": 通过 OpenAI/兼容接口调用，支持 config.api_base 自定义网关
          - "openai-compatible": 任意 OpenAI ChatCompletions 兼容服务（自行配置 api_base）
          - "anthropic": Claude 模型
        - 其它 provider 当前会抛出错误，后续可在 LLMProvider 中扩展
        """
        provider = (model.provider or "").lower()
        try:
            if provider in ("openai", "openai-compatible", "azure-openai"):
                return LLMProvider.create_openai_like_llm(model)
            elif provider in ("anthropic", "claude"):
                return LLMProvider.create_anthropic_llm(model)
            else:
                raise ValueError(
                    f"不支持的provider: {model.provider}，"
                    f"当前支持: openai / openai-compatible / azure-openai / anthropic"
                )
        except Exception as e:
            logger.error(f"创建LLM实例失败: {str(e)}")
            raise

