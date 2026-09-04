from fastapi.testclient import TestClient
import redis

from app.main import app


def test_live_health_echoes_request_id():
    client = TestClient(app)

    response = client.get("/health/live", headers={"X-Request-Id": "req-test-live"})

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "req-test-live"
    payload = response.json()
    assert payload["status"] == "alive"
    assert payload["dependencies"] == {}


def test_ready_health_reports_database_status():
    client = TestClient(app)

    response = client.get("/health/ready", headers={"X-Request-Id": "req-test-ready"})

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "req-test-ready"
    payload = response.json()
    assert payload["status"] in {"ready", "degraded"}
    assert payload["dependencies"]["database"]["status"] == "ok"
    assert "latency_ms" in payload["dependencies"]["database"]
    assert payload["dependencies"]["schema"]["status"] in {
        "ok",
        "optional_outdated",
        "optional_untracked",
    }


def test_agent_health_is_off_by_default_and_never_affects_core_readiness(monkeypatch):
    from app.api import health

    monkeypatch.setattr(health.settings, "ENABLE_AGENT_LAB", False)
    monkeypatch.setattr(health.settings, "AGENT_MODE", "off")

    response = TestClient(app).get("/health/agents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "off"
    assert payload["worker"] == "not_required"
    assert payload["affects_core_readiness"] is False


def test_agent_health_requires_the_dedicated_worker(monkeypatch):
    from app.api import health
    from app.tasks.celery_app import celery_app

    class _Inspect:
        def ping(self):
            return {"celery@host": {"ok": "pong"}}

    monkeypatch.setattr(health.settings, "ENABLE_AGENT_LAB", True)
    monkeypatch.setattr(health.settings, "AGENT_MODE", "shadow")
    monkeypatch.setattr(
        health,
        "_check_redis",
        lambda: health.DependencyHealth(status="ok", latency_ms=0),
    )
    monkeypatch.setattr(celery_app.control, "inspect", lambda timeout: _Inspect())

    response = TestClient(app).get("/health/agents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["worker"] == "unavailable"
    assert payload["affects_core_readiness"] is False


def test_production_readiness_rejects_outdated_schema(monkeypatch):
    from app.api import health

    monkeypatch.setattr(health.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(health, "_expected_schema_revisions", lambda: {"new-head"})
    monkeypatch.setattr(health, "_current_schema_revisions", lambda: {"old-head"})
    monkeypatch.setattr(
        health,
        "_check_redis",
        lambda: health.DependencyHealth(status="ok", latency_ms=0),
    )

    response = TestClient(app).get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["dependencies"]["schema"]["status"] == "outdated"
    assert payload["dependencies"]["schema"]["detail"] == "数据库迁移未到当前版本"


def test_production_readiness_accepts_current_schema(monkeypatch):
    from app.api import health

    monkeypatch.setattr(health.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(health, "_expected_schema_revisions", lambda: {"current-head"})
    monkeypatch.setattr(health, "_current_schema_revisions", lambda: {"current-head"})
    monkeypatch.setattr(
        health,
        "_check_redis",
        lambda: health.DependencyHealth(status="ok", latency_ms=0),
    )

    response = TestClient(app).get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["dependencies"]["schema"]["status"] == "ok"


def test_production_readiness_requires_redis_without_leaking_connection_errors(monkeypatch):
    from app.api import health

    monkeypatch.setattr(health.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        redis.Redis,
        "from_url",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret connection detail")),
    )

    response = TestClient(app).get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["dependencies"]["redis"]["status"] == "down"
    assert payload["dependencies"]["redis"]["detail"] == "Redis 连接失败"


def test_http_error_keeps_detail_and_adds_error_envelope():
    client = TestClient(app)

    response = client.get("/api/cases/999999", headers={"X-Request-Id": "req-test-error"})

    assert response.status_code == 404
    assert response.headers["X-Request-Id"] == "req-test-error"
    payload = response.json()
    assert payload["detail"] == "案件不存在"
    assert payload["error"]["code"] == "http_404"
    assert payload["error"]["request_id"] == "req-test-error"


def test_validation_error_keeps_fastapi_detail_shape():
    client = TestClient(app)

    response = client.post(
        "/api/cases/",
        json={"description": "缺少 occurred_time"},
        headers={"X-Request-Id": "req-test-validation"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert isinstance(payload["detail"], list)
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["request_id"] == "req-test-validation"
