from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import auth
from app.database import Base, get_db
from app.models.user import AuditLog, User
from app.security import AuthMiddleware


def _build_client() -> tuple[TestClient, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    app = FastAPI()

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

    app.add_middleware(
        AuthMiddleware,
        session_factory=session_factory,
        auth_required=True,
        bootstrap_token="bootstrap-test-token",
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
    assert status.json() == {"initialized": False, "bootstrap_available": True}
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
        assert db.query(AuditLog).filter(AuditLog.action == "auth.bootstrap").count() == 1


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
    client, _ = _build_client()
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
    replacement = "a" if token[-1] != "a" else "b"
    client.cookies.set("aicommander_session", token[:-1] + replacement)

    response = client.get("/api/protected")

    assert response.status_code == 401
    assert response.json()["detail"] == "登录状态无效或已过期"
