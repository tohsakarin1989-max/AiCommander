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
    assert settings.AGENT_USE_EXTERNAL_MODEL is False
    assert settings.AGENT_SDK_TRACING_ENABLED is False


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
