"""Retired executors cannot load business data or silently dispatch new tasks."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import agents, assistant
from app.config import settings
from app.database import Base, get_db
from app.models.agent_task import AgentTask


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("enabled,mode", [(False, "off"), (True, "shadow"), (True, "assist")])
@pytest.mark.parametrize("path", ["/api/assistant/chat", "/api/agents/run"])
def test_retired_post_does_not_touch_database_or_echo_inputs(path, enabled, mode, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_AGENT_LAB", enabled)
    monkeypatch.setattr(settings, "AGENT_MODE", mode)
    app = FastAPI()
    app.include_router(assistant.router, prefix="/api/assistant")
    app.include_router(agents.router, prefix="/api/agents")

    def forbidden_db():
        raise AssertionError("retired endpoint attempted database access")

    app.dependency_overrides[get_db] = forbidden_db
    with TestClient(app) as client:
        response = client.post(path, json={"query": "不得回显的合成案情", "case_ids": [123]})
    assert response.status_code == 404
    assert path not in app.openapi()['paths']
    assert "不得回显" not in response.text


def _archive_client(db, role="admin"):
    app = FastAPI()
    app.include_router(agents.router, prefix="/api/agents")

    @app.middleware("http")
    async def bind(request, call_next):
        if role:
            request.state.principal = SimpleNamespace(user_id=1, role=role)
        return await call_next(request)

    def session():
        yield db

    app.dependency_overrides[get_db] = session
    return TestClient(app)


def test_history_remains_readable_when_execution_is_off(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_AGENT_LAB", False)
    monkeypatch.setattr(settings, "AGENT_MODE", "off")
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    db_session.add(AgentTask(query="已有历史问题", result={"facts": ["原有记录"]}, status="completed"))
    db_session.commit()
    with _archive_client(db_session) as client:
        result = client.get("/api/agents/tasks")
        assert result.status_code == 200
        assert result.json()[0]["result"] == {"facts": ["原有记录"]}
        assert client.get("/api/agents/tasks?limit=201").status_code == 422
    assert db_session.query(AgentTask).count() == 1


@pytest.mark.parametrize("role", ["analyst", "viewer", None])
def test_legacy_global_archive_stays_admin_only(db_session, monkeypatch, role):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    with _archive_client(db_session, role) as client:
        assert client.get("/api/agents/tasks").status_code == (401 if role is None else 403)


def test_archive_without_scope_provenance_rejects_restricted_session(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    db_session.info["authorized_area_ids"] = (1,)
    with _archive_client(db_session) as client:
        response = client.get("/api/agents/tasks")
    assert response.status_code == 403
    assert "仅限全域管理员" in response.json()["detail"]


def test_real_middleware_keeps_retired_paths_authenticated():
    from tests.test_auth_security import _build_client, _bootstrap_admin

    client, _ = _build_client()
    client.app.include_router(assistant.router, prefix="/api/assistant")
    client.app.include_router(agents.router, prefix="/api/agents")
    with client:
        assert client.post("/api/assistant/chat", json={"query": "x"}).status_code == 401
        assert client.post("/api/agents/run", json={"query": "x"}).status_code == 401
        assert _bootstrap_admin(client).status_code in (200, 201)
        assert client.post("/api/assistant/chat", json={"query": "x"}).status_code == 404
        assert client.post("/api/agents/run", json={"query": "x"}).status_code == 404
