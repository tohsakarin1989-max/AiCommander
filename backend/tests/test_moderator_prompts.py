"""验证 moderator 报告 schema 包含新增字段"""
import inspect
from unittest.mock import MagicMock
from app.ai.agents.moderator import ModeratorAgent


def make_moderator():
    model = MagicMock()
    llm = MagicMock()
    return ModeratorAgent(model, llm)


def test_final_report_prompt_contains_risk_trend():
    agent = make_moderator()
    source = inspect.getsource(agent.generate_final_report)
    assert "risk_trend" in source


def test_final_report_prompt_contains_infrastructure_risks():
    agent = make_moderator()
    source = inspect.getsource(agent.generate_final_report)
    assert "infrastructure_risks" in source
