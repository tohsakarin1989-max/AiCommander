"""Agent 叙述层适配器。

确定性工具负责事实和证据；OpenAI Agents SDK 只读取脱敏后的特征摘要，
用于整理表达。SDK 采用惰性导入，关闭外部模型时不影响核心服务启动。
"""
from __future__ import annotations

import json
from typing import Any, Optional, Protocol

from pydantic import BaseModel, Field

from app.config import settings


class AgentNarrator(Protocol):
    provider_name: str
    model_name: str

    async def summarize(self, query: str, payload: dict[str, Any]) -> dict[str, Any]: ...


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

    async def summarize(self, query: str, payload: dict[str, Any]) -> dict[str, Any]:
        from agents import Agent, RunConfig, Runner

        agent = Agent(
            name="油盾双域研判智能体",
            model=self.model_name,
            instructions=(
                "你只整理系统提供的脱敏、确定性分析结果。区分事实、推断、建议和信息缺口；"
                "不得补写人员、车辆、井名、坐标或案件事实；不得进行犯罪预测、自动确认串并案或"
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
            return output.model_dump()
        return AgentNarrative.model_validate(output).model_dump()


def build_narrator() -> Optional[AgentNarrator]:
    if not settings.AGENT_USE_EXTERNAL_MODEL:
        return None
    if settings.AGENT_EXTERNAL_DATA_POLICY != "redacted_only":
        return None
    if settings.AGENT_PROVIDER == "openai_agents":
        return OpenAIAgentsNarrator(settings.AGENT_MODEL)
    return None
