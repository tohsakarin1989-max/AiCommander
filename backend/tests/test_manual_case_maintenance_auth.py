"""Exercise real cookie authentication before legacy maintenance routes."""
import pytest

from test_auth_security import _bootstrap_admin, _build_client


@pytest.mark.parametrize("path", [
    "/api/cases/1/preprocess", "/api/cases/preprocess/batch", "/api/cases/batch-review",
    "/api/conclusions/draft",
])
def test_only_admin_can_call_manual_case_maintenance(path):
    client, _ = _build_client()
    # Minimal endpoint makes middleware acceptance explicit without invoking models.
    client.app.add_api_route(path, lambda: {"ok": True}, methods=["POST"])
    assert client.post(path).status_code == 401
    assert _bootstrap_admin(client).status_code in {200, 201}
    assert client.post(path).status_code == 200
    for role in ("analyst", "viewer"):
        response = client.post("/api/auth/users", json={
            "username": f"maintenance-{role}", "display_name": "合成测试用户",
            "password": "StrongPassword!2026", "role": role,
        })
        assert response.status_code in {200, 201}, response.text
    for role in ("analyst", "viewer"):
        client.cookies.clear()
        assert client.post("/api/auth/login", json={
            "username": f"maintenance-{role}", "password": "StrongPassword!2026",
        }).status_code == 200
        assert client.post(path).status_code == 403
        # Ordinary authorized writes keep their existing permission contract.
        assert client.post("/api/protected").status_code == (200 if role == "analyst" else 403)
