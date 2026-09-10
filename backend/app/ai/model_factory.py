from app.models.ai_model import AIModel
from app.ai.llm_providers import LLMProvider
from langchain_core.language_models.chat_models import BaseChatModel
from app.utils.logger import logger
from app.config import settings
from urllib.parse import urlparse


class ModelFactory:
    """AI模型工厂，根据配置创建LLM实例"""

    def create_llm(
        self,
        model: AIModel,
        *,
        data_classification: str = "raw",
    ) -> BaseChatModel:
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
            self._assert_data_egress_allowed(
                model,
                provider=provider,
                data_classification=data_classification,
            )
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

    @staticmethod
    def _assert_data_egress_allowed(
        model: AIModel,
        *,
        provider: str,
        data_classification: str,
    ) -> None:
        if data_classification not in {"raw", "redacted"}:
            raise ValueError("不支持的模型数据分级")
        if ModelFactory._is_trusted_local_endpoint(model, provider):
            return
        if data_classification != "redacted":
            raise ValueError("原始案件和精确生产数据禁止发送外部模型")
        if settings.MODEL_DATA_EGRESS_POLICY != "external_redacted_only":
            raise ValueError("当前配置禁止调用外部模型")

    @staticmethod
    def _is_trusted_local_endpoint(model: AIModel, provider: str) -> bool:
        if provider not in {"openai", "openai-compatible", "azure-openai"}:
            return False
        api_base = str((model.config or {}).get("api_base") or "").strip()
        if not api_base:
            return False
        parsed = urlparse(api_base)
        allowed_hosts = {
            item.strip().lower()
            for item in settings.TRUSTED_LOCAL_MODEL_HOSTS.split(",")
            if item.strip()
        }
        return parsed.scheme in {"http", "https"} and (parsed.hostname or "").lower() in allowed_hosts
