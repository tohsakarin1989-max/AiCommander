import pytest

from app.api import runtime


@pytest.mark.parametrize("enabled", [False, True])
def test_runtime_features_reflect_actual_settings_without_secrets(db_session, monkeypatch, enabled):
    monkeypatch.setattr(runtime, "_redis_status", lambda: "ok")
    for setting in (
        "ENABLE_LEGACY_OPERATIONS_MODULES", "ENABLE_BONUS_ACCOUNTING",
        "ENABLE_AGENT_LAB", "ENABLE_SHOWCASE",
    ):
        monkeypatch.setattr(runtime.settings, setting, enabled)

    payload = runtime.runtime_status(db_session).model_dump()

    assert payload["features"] == {
        "legacy_operations": enabled,
        "bonus_accounting": enabled,
        "agent_lab": enabled,
        "showcase": enabled,
    }
    assert all(isinstance(value, bool) for value in payload["features"].values())
    assert "SECRET_KEY" not in payload
    assert "DATABASE_URL" not in payload


def test_runtime_features_are_independent_of_cache_health(db_session, monkeypatch):
    monkeypatch.setattr(runtime, "_redis_status", lambda: "unavailable")
    monkeypatch.setattr(runtime.settings, "ENABLE_BONUS_ACCOUNTING", True)
    payload = runtime.runtime_status(db_session).model_dump()
    assert payload["status"] == "degraded"
    assert payload["features"]["bonus_accounting"] is True
