"""Agent 叙述层适配器。

确定性工具负责事实和证据；OpenAI Agents SDK 只读取脱敏后的特征摘要，
用于整理表达。SDK 采用惰性导入，关闭外部模型时不影响核心服务启动。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Optional, Protocol

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.model_factory import ModelFactory
from app.config import settings
from app.models.ai_model import AIModel


@dataclass(frozen=True)
class AgentNarrationUsage:
    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return max(0, self.input_tokens) + max(0, self.output_tokens)


@dataclass(frozen=True)
class AgentNarrationOutcome:
    content: dict[str, Any]
    usage: AgentNarrationUsage = field(default_factory=AgentNarrationUsage)


class AgentNarrator(Protocol):
    provider_name: str
    model_name: str
    input_cost_per_million_usd: float
    output_cost_per_million_usd: float

    async def summarize(
        self,
        query: str,
        payload: dict[str, Any],
    ) -> AgentNarrationOutcome | dict[str, Any]: ...


class AgentNarrative(BaseModel):
    result: str
    inferences: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    boundary: list[str] = Field(default_factory=list)


class OpenAIAgentsNarrator:
    provider_name = "openai_agents"

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.input_cost_per_million_usd = settings.AGENT_MODEL_INPUT_COST_PER_MILLION_USD
        self.output_cost_per_million_usd = settings.AGENT_MODEL_OUTPUT_COST_PER_MILLION_USD

    async def summarize(self, query: str, payload: dict[str, Any]) -> AgentNarrationOutcome:
        if settings.MODEL_DATA_EGRESS_POLICY != "external_redacted_only":
            raise RuntimeError("当前配置禁止 OpenAI Agents 外发")
        if settings.AGENT_EXTERNAL_DATA_POLICY != "redacted_only":
            raise RuntimeError("OpenAI Agents 只能处理脱敏特征")
        from agents import Agent, RunConfig, Runner

        agent = Agent(
            name="油盾双域研判智能体",
            model=self.model_name,
            instructions=(
                "你只整理系统提供的脱敏、确定性分析结果。"
                "区分事实、推断、建议和信息缺口；不得补写人员、车辆、井名、坐标或案件事实；"
                "不得进行犯罪预测、自动确认串并案或"
                "声称已经执行处置。每个有效结论必须保留输入中的临时证据编号。"
            ),
            output_type=AgentNarrative,
        )
        result = await Runner.run(
            agent,
            json.dumps({"task_goal": query, "analysis": payload}, ensure_ascii=False, default=str),
            max_turns=2,
            run_config=RunConfig(
                workflow_name="aicommander_agent_lab",
                tracing_disabled=not settings.AGENT_SDK_TRACING_ENABLED,
                trace_include_sensitive_data=False,
            ),
        )
        output = result.final_output
        if isinstance(output, AgentNarrative):
            content = output.model_dump()
        else:
            content = AgentNarrative.model_validate(output).model_dump()
        usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
        return AgentNarrationOutcome(
            content=content,
            usage=AgentNarrationUsage(
                request_count=_usage_value(usage, "requests"),
                input_tokens=_usage_value(usage, "input_tokens"),
                output_tokens=_usage_value(usage, "output_tokens"),
            ),
        )


class ModelRegistryNarrator:
    """复用系统现有模型注册表，兼容 OpenAI-like 与 Anthropic 提供方。"""

    def __init__(self, model: AIModel) -> None:
        self._model = model
        self.provider_name = str(model.provider or "configured").strip().lower()
        self.model_name = model.model_name
        config = dict(model.config or {})
        self.input_cost_per_million_usd = _safe_price(
            config.get("input_cost_per_million_usd")
        )
        self.output_cost_per_million_usd = _safe_price(
            config.get("output_cost_per_million_usd")
        )

    async def summarize(self, query: str, payload: dict[str, Any]) -> AgentNarrationOutcome:
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = ModelFactory().create_llm(
            self._model,
            data_classification="redacted",
        )
        response = await llm.ainvoke([
            SystemMessage(content=(
                "你只整理系统提供的脱敏、确定性分析结果。必须返回JSON对象，"
                "字段为result、"
                "inferences、recommendations、information_gaps、boundary。不得补写人员、车辆、"
                "井名、坐标或案件事实，不得进行犯罪预测、自动确认串并案或"
                "声称已经执行处置。"
            )),
            HumanMessage(content=json.dumps(
                {"task_goal": query, "analysis": payload},
                ensure_ascii=False,
                default=str,
            )),
        ])
        content = AgentNarrative.model_validate(
            json.loads(_response_text(getattr(response, "content", response)))
        ).model_dump()
        usage_payload = getattr(response, "usage_metadata", None) or {}
        if not usage_payload:
            metadata = getattr(response, "response_metadata", None) or {}
            usage_payload = metadata.get("token_usage") or metadata.get("usage") or {}
        return AgentNarrationOutcome(
            content=content,
            usage=AgentNarrationUsage(
                request_count=1,
                input_tokens=_first_usage_value(
                    usage_payload,
                    "input_tokens",
                    "prompt_tokens",
                    "input_token_count",
                ),
                output_tokens=_first_usage_value(
                    usage_payload,
                    "output_tokens",
                    "completion_tokens",
                    "output_token_count",
                ),
            ),
        )


def _usage_value(value: Any, field_name: str) -> int:
    raw = getattr(value, field_name, 0) if value is not None else 0
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _first_usage_value(value: Any, *field_names: str) -> int:
    for field_name in field_names:
        raw = value.get(field_name) if isinstance(value, dict) else getattr(value, field_name, None)
        if raw is None:
            continue
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            continue
    return 0


def _safe_price(value: Any) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _response_text(content: Any) -> str:
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(getattr(item, "text", "")))
        text = "".join(parts).strip()
    else:
        text = str(content).strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    return text


def build_narrator(db: Session | None = None) -> Optional[AgentNarrator]:
    if not settings.AGENT_USE_EXTERNAL_MODEL:
        return None
    if settings.AGENT_EXTERNAL_DATA_POLICY != "redacted_only":
        return None
    if settings.MODEL_DATA_EGRESS_POLICY != "external_redacted_only":
        return None
    if settings.AGENT_PROVIDER == "openai_agents":
        return OpenAIAgentsNarrator(settings.AGENT_MODEL)
    if settings.AGENT_PROVIDER == "model_registry" and db is not None:
        model = db.query(AIModel).filter(
            AIModel.id == settings.AGENT_MODEL_ID,
            AIModel.is_active.is_(True),
        ).first()
        if model is None:
            raise ValueError("agent_model_registry_entry_unavailable")
        return ModelRegistryNarrator(model)
    return None
