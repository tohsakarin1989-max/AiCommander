from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from app.models.ai_model import AIModel
from typing import Any, Dict
from app.utils.logger import logger
from app.utils.encryption import decrypt_api_key


class LLMProvider:
    """
    LLM提供商封装（通用协议）：
    - provider 字段用于选择后端实现：
      - openai: 使用 OpenAI 官方/兼容接口（可通过 config.api_base 指向自建网关或 Azure）
      - anthropic: 使用 Claude 接口
      - openai-compatible: 显式声明为任意 OpenAI Chat Completions 兼容服务
      - 其它值：当前会抛出错误，后续可扩展自定义实现
    - config 字段提供通用参数：
      - temperature: 采样温度
      - max_tokens: 最大生成token
      - api_base: OpenAI兼容后端的自定义 base URL
    """

    @staticmethod
    def _get_api_key(model: AIModel) -> str:
        """从模型配置中解密获取API Key"""
        try:
            return decrypt_api_key(model.api_key)
        except Exception as e:
            logger.error(f"解密API Key失败: {e}")
            raise

    @staticmethod
    def _base_params(model: AIModel) -> Dict[str, Any]:
        config = model.config or {}
        return {
            "temperature": config.get("temperature", 0.7),
            "max_tokens": config.get("max_tokens", 2000),
        }

    @staticmethod
    def create_openai_like_llm(model: AIModel) -> ChatOpenAI:
        """
        创建 OpenAI 或 OpenAI兼容接口的 LLM 实例：
        - 对于 provider = openai / openai-compatible / azure-openai / qwen-*-openai 等，
          都可以通过 config.api_base 指定兼容的 HTTP 端点。
        """
        api_key = LLMProvider._get_api_key(model)
        config = model.config or {}
        params = LLMProvider._base_params(model)

        # 支持自定义 base_url（如自建网关、Azure OpenAI、Ollama/OpenAI兼容服务等）
        api_base = config.get("api_base")

        return ChatOpenAI(
            model=model.model_name,
            openai_api_key=api_key,
            base_url=api_base,
            **params,
        )

    @staticmethod
    def create_anthropic_llm(model: AIModel) -> ChatAnthropic:
        """创建 Anthropic Claude LLM 实例"""
        api_key = LLMProvider._get_api_key(model)
        params = LLMProvider._base_params(model)

        return ChatAnthropic(
            model=model.model_name,
            anthropic_api_key=api_key,
            **params,
        )