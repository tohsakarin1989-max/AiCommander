"""验证 analyst prompt 包含涉油专业化内容"""
import pytest
from unittest.mock import MagicMock
from app.ai.agents.analyst import AnalystAgent


def make_agent(specialty=None):
    model = MagicMock()
    model.config = {"specialty": specialty}
    llm = MagicMock()
    return AnalystAgent(model, llm, specialty=specialty)


def test_spatial_prompt_mentions_pipeline():
    agent = make_agent("spatial")
    prompt = agent._build_analysis_prompt("测试案件信息")
    assert "管线" in prompt or "输油" in prompt


def test_modus_prompt_mentions_oil_theft_methods():
    agent = make_agent("modus")
    prompt = agent._build_analysis_prompt("测试案件信息")
    assert "打孔" in prompt or "盗油" in prompt


def test_prevention_prompt_mentions_pipeline_company():
    agent = make_agent("prevention")
    prompt = agent._build_analysis_prompt("测试案件信息")
    assert "管道" in prompt or "油田" in prompt or "保卫" in prompt


def test_all_specialties_produce_nonempty_prompt():
    for specialty in ["temporal", "spatial", "modus", "prevention", None]:
        agent = make_agent(specialty)
        prompt = agent._build_analysis_prompt("案件信息")
        assert len(prompt) > 100
