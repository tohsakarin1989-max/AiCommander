import pytest
from pydantic import ValidationError

from app.config import Settings


BASE = {
    "SECRET_KEY": "test-secret-key-for-agent-config",
    "_env_file": None,
}


def test_agent_lab_defaults_to_fail_closed():
    settings = Settings(**BASE)

    assert settings.ENABLE_AGENT_LAB is False
    assert settings.AGENT_MODE == "off"
    assert settings.AGENT_MUTATIONS_ENABLED is False
    assert settings.AGENT_EXTERNAL_DATA_POLICY == "redacted_only"
    assert settings.AGENT_MAX_STEPS == 8
    assert settings.AGENT_TIMEOUT_SECONDS == 120
    assert settings.AGENT_REDIS_QUEUE == "agent_lab"
    assert settings.AGENT_PROVIDER == "deterministic"
    assert settings.AGENT_MODEL == ""
    assert settings.AGENT_USE_EXTERNAL_MODEL is False
    assert settings.AGENT_SDK_TRACING_ENABLED is False
    assert settings.AGENT_MAP_PILOT_MAX_ASSETS == 100


def test_agent_mutations_require_assist_mode():
    try:
        Settings(
            **BASE,
            ENABLE_AGENT_LAB=True,
            AGENT_MODE="shadow",
            AGENT_MUTATIONS_ENABLED=True,
        )
    except ValueError as exc:
        assert "assist" in str(exc)
    else:
        raise AssertionError("shadow 模式不应允许正式数据写入")


@pytest.mark.parametrize(
    ("provider", "api_key", "model"),
    [
        ("deterministic", None, ""),
        ("openai_agents", None, "gpt-5-mini"),
        ("openai_agents", "sk-test-placeholder", ""),
    ],
)
def test_external_model_requires_explicit_complete_configuration(provider, api_key, model):
    with pytest.raises(ValidationError):
        Settings(
            **BASE,
            AGENT_USE_EXTERNAL_MODEL=True,
            AGENT_PROVIDER=provider,
            AGENT_MODEL=model,
            OPENAI_API_KEY=api_key,
        )


def test_external_openai_adapter_is_optional_and_explicit():
    settings = Settings(
        **BASE,
        AGENT_USE_EXTERNAL_MODEL=True,
        AGENT_PROVIDER="openai_agents",
        AGENT_MODEL="gpt-5-mini",
        OPENAI_API_KEY="sk-test-placeholder",
    )

    assert settings.AGENT_PROVIDER == "openai_agents"
    assert settings.AGENT_USE_EXTERNAL_MODEL is True


@pytest.mark.parametrize("limit", [0, 501])
def test_map_pilot_asset_limit_is_bounded(limit):
    with pytest.raises(ValidationError):
        Settings(**BASE, AGENT_MAP_PILOT_MAX_ASSETS=limit)
