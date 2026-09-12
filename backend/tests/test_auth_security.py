from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import auth
from app.database import Base, get_db
from app.models.user import AuditLog, User, UserSession
from app.models.map_foundation import OperationalArea, UserAreaScope
from app.security import AuthMiddleware


def _build_client(
    *,
    environment: str = "development",
    bootstrap_token: str = "bootstrap-test-token",
) -> tuple[TestClient, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    app = FastAPI()
    app.state.environment = environment

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(auth.router, prefix="/api/auth")

    @app.get("/api/protected")
    def protected():
        return {"ok": True}

    @app.post("/api/protected")
    def protected_write():
        return {"ok": True}

    @app.post("/api/deployment-recommendations/demo/feedback")
    def deployment_feedback():
        return {"ok": True}

    @app.post("/api/deployment/smart-analysis")
    def legacy_deployment_write():
        return {"ok": True}

    @app.get("/api/jurisdiction/assets")
    def map_assets_read():
        return {"ok": True}

    @app.post("/api/jurisdiction/assets")
    def map_assets_write():
        return {"ok": True}

    @app.get("/api/patrols")
    def legacy_patrols():
        return {"ok": True}

    @app.get("/api/events")
    def legacy_events():
        return {"ok": True}

    @app.get("/api/key-locations")
    def legacy_key_locations():
        return {"ok": True}

    app.add_middleware(
        AuthMiddleware,
        session_factory=session_factory,
        auth_required=True,
        bootstrap_token=bootstrap_token,
        secure_cookie=False,
        allowed_origins=("http://testserver",),
    )
    return TestClient(app), session_factory


def _bootstrap_admin(client: TestClient):
    return client.post(
        "/api/auth/bootstrap",
        headers={"X-Bootstrap-Token": "bootstrap-test-token"},
        json={
            "username": "administrator",
            "display_name": "系统管理员",
            "password": "StrongPassword!2026",
        },
    )


def test_protected_api_rejects_anonymous_requests():
    client, _ = _build_client()

    response = client.get("/api/protected")

    assert response.status_code == 401
    assert response.json()["detail"] == "请先登录"


def test_bootstrap_requires_one_time_token_and_creates_admin_session():
    client, session_factory = _build_client()

    status = client.get("/api/auth/bootstrap-status")
    denied = client.post(
        "/api/auth/bootstrap",
        json={"username": "administrator", "password": "StrongPassword!2026"},
    )
    created = _bootstrap_admin(client)

    assert status.status_code == 200
    assert status.json() == {
        "initialized": False,
        "bootstrap_available": True,
        "local_bootstrap_available": True,
    }
    assert denied.status_code == 403
    assert created.status_code == 201
    assert created.json()["user"]["role"] == "admin"
    assert "aicommander_session=" in created.headers["set-cookie"]
    assert "HttpOnly" in created.headers["set-cookie"]

    protected = client.get("/api/protected")
    assert protected.status_code == 200

    duplicate = _bootstrap_admin(client)
    assert duplicate.status_code == 409

    with session_factory() as db:
        user = db.query(User).one()
        assert user.username == "administrator"
        assert user.password_hash != "StrongPassword!2026"
        assert user.role == "admin"
        assert db.query(OperationalArea).filter(OperationalArea.is_default.is_(True)).count() == 1
        scope = db.query(UserAreaScope).filter(UserAreaScope.user_id == user.id).one()
        assert scope.access_level == "manage"
        default_area_id = scope.operational_area_id
        assert db.query(AuditLog).filter(AuditLog.action == "auth.bootstrap").count() == 1

    scopes = client.get("/api/auth/me/area-scopes")
    assert scopes.status_code == 200
    assert scopes.json() == [
        {
            "operational_area_id": default_area_id,
            "area_code": "default-factory",
            "area_name": "默认厂区",
            "access_level": "manage",
            "is_default": True,
        }
    ]


def test_local_development_bootstrap_does_not_require_token():
    client, _ = _build_client(bootstrap_token="")

    status_response = client.get("/api/auth/bootstrap-status")
    created = client.post(
        "/api/auth/bootstrap-local",
        json={
            "username": "administrator",
            "display_name": "系统管理员",
            "password": "StrongPassword!2026",
        },
    )

    assert status_response.json() == {
        "initialized": False,
        "bootstrap_available": False,
        "local_bootstrap_available": True,
    }
    assert created.status_code == 201
    assert created.json()["user"]["role"] == "admin"
    assert client.get("/api/protected").status_code == 200


def test_local_bootstrap_is_closed_outside_development():
    client, _ = _build_client(environment="production", bootstrap_token="")

    status_response = client.get("/api/auth/bootstrap-status")
    denied = client.post(
        "/api/auth/bootstrap-local",
        json={"username": "administrator", "password": "StrongPassword!2026"},
    )

    assert status_response.json()["local_bootstrap_available"] is False
    assert denied.status_code == 403


def test_login_lockout_logout_and_session_revocation():
    client, session_factory = _build_client()
    assert _bootstrap_admin(client).status_code == 201
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/protected").status_code == 401

    for _ in range(5):
        failed = client.post(
            "/api/auth/login",
            json={"username": "administrator", "password": "wrong-password"},
        )
        assert failed.status_code == 401

    locked = client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "StrongPassword!2026"},
    )
    assert locked.status_code == 423

    with session_factory() as db:
        user = db.query(User).one()
        user.locked_until = datetime.utcnow()
        db.commit()

    login = client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "StrongPassword!2026"},
    )
    assert login.status_code == 200
    assert client.get("/api/protected").status_code == 200


def test_admin_can_create_viewer_and_viewer_is_read_only():
    client, session_factory = _build_client()
    assert _bootstrap_admin(client).status_code == 201

    created = client.post(
        "/api/auth/users",
        json={
            "username": "viewer01",
            "display_name": "只读用户",
            "password": "ViewerPassword!2026",
            "role": "viewer",
        },
    )
    assert created.status_code == 201
    assert created.json()["role"] == "viewer"

    assert client.post("/api/auth/logout").status_code == 204
    login = client.post(
        "/api/auth/login",
        json={"username": "viewer01", "password": "ViewerPassword!2026"},
    )
    assert login.status_code == 200
    assert client.get("/api/protected").status_code == 200
    assert client.post("/api/protected").status_code == 403
    assert client.get("/api/auth/users").status_code == 403

    token = client.cookies.get("aicommander_session")
    untrusted = client.post("/api/auth/logout", headers={"Origin": "https://untrusted.example"})
    assert untrusted.status_code == 403
    assert client.get("/api/auth/me").status_code == 200
    assert client.delete("/api/auth/logout").status_code == 403

    logged_out = client.post("/api/auth/logout", headers={"Origin": "http://testserver"})
    assert logged_out.status_code == 204
    assert "Max-Age=0" in logged_out.headers["set-cookie"]
    assert client.cookies.get("aicommander_session") is None
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/protected", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    with session_factory() as db:
        session = db.query(UserSession).filter(UserSession.user_id == created.json()["id"]).one()
        assert session.revoked_at is not None
        assert db.query(AuditLog).filter(
            AuditLog.user_id == created.json()["id"],
            AuditLog.action == "api.mutation",
            AuditLog.path == "/api/auth/logout",
            AuditLog.status_code == 204,
        ).count() == 1


def test_analyst_can_submit_recommendation_feedback_but_not_legacy_deployment():
    client, _ = _build_client()
    assert _bootstrap_admin(client).status_code == 201
    created = client.post(
        "/api/auth/users",
        json={
            "username": "analyst01",
            "display_name": "分析员",
            "password": "AnalystPassword!2026",
            "role": "analyst",
        },
    )
    assert created.status_code == 201
    assert client.post("/api/auth/logout").status_code == 204
    assert client.post(
        "/api/auth/login",
        json={"username": "analyst01", "password": "AnalystPassword!2026"},
    ).status_code == 200

    assert client.post("/api/deployment-recommendations/demo/feedback").status_code == 200
    assert client.post("/api/deployment/smart-analysis").status_code == 403
    assert client.get("/api/jurisdiction/assets").status_code == 200
    assert client.post("/api/jurisdiction/assets").status_code == 403
    assert client.get("/api/patrols").status_code == 403
    assert client.get("/api/events").status_code == 200
    assert client.get("/api/key-locations").status_code == 403


def test_admin_can_replace_user_area_scopes():
    client, session_factory = _build_client()
    assert _bootstrap_admin(client).status_code == 201
    created = client.post(
        "/api/auth/users",
        json={
            "username": "scoped01",
            "display_name": "辖区分析员",
            "password": "ScopedPassword!2026",
            "role": "analyst",
        },
    )
    with session_factory() as db:
        second = OperationalArea(code="second", name="第二厂区", status="active")
        db.add(second)
        db.commit()
        db.refresh(second)

    response = client.put(
        f"/api/auth/users/{created.json()['id']}/area-scopes",
        json={"scopes": [{"operational_area_id": second.id, "access_level": "read"}]},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "operational_area_id": second.id,
            "area_code": "second",
            "area_name": "第二厂区",
            "access_level": "read",
        }
    ]
    assert client.post("/api/auth/logout").status_code == 204
    assert client.post(
        "/api/auth/login",
        json={"username": "scoped01", "password": "ScopedPassword!2026"},
    ).status_code == 200
    assert client.get("/api/auth/me/area-scopes").json() == [
        {
            "operational_area_id": second.id,
            "area_code": "second",
            "area_name": "第二厂区",
            "access_level": "read",
            "is_default": False,
        }
    ]


def test_cookie_authenticated_writes_reject_untrusted_origin():
    client, _ = _build_client()
    assert _bootstrap_admin(client).status_code == 201

    response = client.post(
        "/api/protected",
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "请求来源不受信任"


def test_tampered_session_cookie_is_rejected():
    client, _ = _build_client()
    assert _bootstrap_admin(client).status_code == 201
    token = client.cookies.get("aicommander_session")
    assert token
    header, payload, signature = token.split(".")
    replacement = "a" if signature[0] != "a" else "b"
    client.cookies.set(
        "aicommander_session",
        f"{header}.{payload}.{replacement}{signature[1:]}",
    )

    response = client.get("/api/protected")

    assert response.status_code == 401
    assert response.json()["detail"] == "登录状态无效或已过期"


def test_noncanonical_session_signature_encoding_is_rejected():
    client, _ = _build_client()
    assert _bootstrap_admin(client).status_code == 201
    token = client.cookies.get("aicommander_session")
    assert token
    header, payload, signature = token.split(".")

    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    final_index = alphabet.index(signature[-1])
    noncanonical_final = alphabet[(final_index // 4) * 4 + 1]
    if noncanonical_final == signature[-1]:
        noncanonical_final = alphabet[(final_index // 4) * 4 + 2]
    client.cookies.set(
        "aicommander_session",
        f"{header}.{payload}.{signature[:-1]}{noncanonical_final}",
    )

    response = client.get("/api/protected")

    assert response.status_code == 401
    assert response.json()["detail"] == "登录状态无效或已过期"
