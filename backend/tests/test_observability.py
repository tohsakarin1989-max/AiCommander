from fastapi.testclient import TestClient

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
