from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth, case_results
from app.database import Base, bind_principal_scope, get_db
from app.models.case import Case
from app.models.case_result import CaseResultSnapshot
from app.models.map_foundation import MapSnapshot, OperationalArea, UserAreaScope
from app.security import AuthMiddleware
from app.services.auth_service import AuthService
from app.services.case_result_service import CaseResultService
from test_case_result_access import result_data  # noqa: F401


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as db:
        yield db
    engine.dispose()


def client_for(db, role="analyst"):
    app = FastAPI()
    app.include_router(case_results.router, prefix="/api")

    @app.middleware("http")
    async def test_principal(request, call_next):
        if role:
            request.state.principal = SimpleNamespace(role=role, user_id=1)
        return await call_next(request)

    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def prepare(db):
    db.info.update(authorized_area_ids=(1,), area_access_levels={1: "write"})
    db.execute(MapSnapshot.__table__.update().values(status="current"))
    db.commit()


def test_generate_read_history_and_idempotency_without_case_changes(db_session, result_data):
    prepare(db_session)
    original = db_session.scalar(select(Case.description).where(Case.id == 1))
    with client_for(db_session) as client:
        first = client.post("/api/cases/1/results")
        assert first.status_code == 201, first.text
        result = first.json()
        assert result["content"]["candidates"][0]["title"] == "测试候选"
        duplicate = client.post("/api/cases/1/results")
        assert duplicate.status_code == 200
        assert duplicate.json()["id"] == result["id"]
        assert client.get(first.headers["location"]).json() == result
        assert first.headers["cache-control"] == "no-store"
        history = client.get("/api/cases/1/results/history").json()
        assert len(history["items"]) == 1 and not history["has_more"]
    assert db_session.scalar(select(Case.description).where(Case.id == 1)) == original


def test_history_retains_frozen_content_after_original_input_change(db_session, result_data):
    prepare(db_session)
    saved, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    db_session.execute(Case.__table__.update().where(Case.id == 1).values(description="后来修改"))
    db_session.commit()
    assert CaseResultService.read(db_session, saved["id"]) == saved


def test_snapshot_creation_respects_callers_transaction_rollback(db_session, result_data):
    prepare(db_session)
    saved, _ = CaseResultService.create_current(db_session, 1)
    db_session.rollback()
    assert db_session.scalar(select(CaseResultSnapshot.id).where(CaseResultSnapshot.id == saved["id"])) is None


def test_changed_derived_content_creates_new_snapshot_without_overwriting_old(db_session, result_data):
    prepare(db_session)
    original, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    candidate = result_data[2]
    candidate.title = "后续候选说明"
    db_session.commit()
    changed, created = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    assert created and changed["id"] != original["id"]
    assert CaseResultService.read(db_session, original["id"])["content"]["candidates"][0]["title"] == "测试候选"
    first = CaseResultService.history(db_session, 1, limit=1)
    second = CaseResultService.history(db_session, 1, limit=1, offset=1)
    assert first["has_more"] and not second["has_more"]
    assert {first["items"][0]["id"], second["items"][0]["id"]} == {original["id"], changed["id"]}


def test_revoke_evidence_hides_body_and_history_details(db_session, result_data):
    prepare(db_session)
    profile, run, candidate = result_data
    candidate.evidence_refs = ["case:2"]
    db_session.commit()
    db_session.info["authorized_area_ids"] = (1, 2)
    saved, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    db_session.info["authorized_area_ids"] = (1,)
    with client_for(db_session, "viewer") as client:
        response = client.get(f"/api/case-results/{saved['id']}")
        assert response.status_code == 404
        assert "测试候选" not in response.text and "case:2" not in response.text
        item = client.get("/api/cases/1/results/history").json()["items"][0]
        assert item == {"id": saved["id"], "availability": "unavailable"}
        assert client.post("/api/cases/1/results").status_code == 403
    db_session.info["authorized_area_ids"] = (2,)
    assert list(db_session.scalars(select(CaseResultSnapshot.id))) == []


def test_missing_login_scope_and_bad_pagination_rejected(db_session, result_data):
    prepare(db_session)
    with client_for(db_session, None) as client:
        assert client.get("/api/cases/1/results/history").status_code == 401
        assert client.post("/api/cases/1/results").status_code == 401
    with client_for(db_session) as client:
        assert client.get("/api/cases/1/results/history?limit=101").status_code == 422
        assert client.post("/api/cases/2/results").status_code == 404
        db_session.info["area_access_levels"] = {1: "read"}
        assert client.post("/api/cases/1/results").status_code == 403
        db_session.info.pop("authorized_area_ids")
        assert client.get("/api/cases/1/results/history").status_code == 404


def test_invalid_derived_input_returns_conflict_without_persisting(db_session, result_data):
    prepare(db_session)
    result_data[2].supporting_evidence = []
    db_session.commit()
    with client_for(db_session) as client:
        response = client.post("/api/cases/1/results")
        assert response.status_code == 409
        assert "result_candidate_missing_evidence" not in response.text
    assert list(db_session.scalars(select(CaseResultSnapshot.id))) == []


def test_real_login_and_persisted_scope_revocation(db_session, result_data):
    # No injected principal: authenticate a real session cookie, then bind each
    # fresh request's scope through the same function used by production get_db.
    db_session.execute(OperationalArea.__table__.update().where(OperationalArea.id == 1).values(is_default=True))
    db_session.execute(MapSnapshot.__table__.update().values(status="current"))
    user = AuthService.create_user(db_session, username="result-analyst", display_name="合成用户",
                                   password="Synthetic-result!2026", role="analyst")
    user_id = user.id
    db_session.commit()
    factory = sessionmaker(bind=db_session.bind, autoflush=False)
    app = FastAPI()
    app.state.environment = "test"
    app.include_router(auth.router, prefix="/api/auth")
    app.include_router(case_results.router, prefix="/api")

    def request_db(request: Request):
        with factory() as db:
            bind_principal_scope(db, getattr(request.state, "principal", None), method=request.method)
            yield db

    app.dependency_overrides[get_db] = request_db
    app.add_middleware(AuthMiddleware, session_factory=factory, auth_required=True,
                       bootstrap_token="", secure_cookie=False, allowed_origins=("http://testserver",))
    with TestClient(app) as client:
        assert client.get("/api/cases/1/results/history").status_code == 401
        login = client.post("/api/auth/login", json={"username": "result-analyst", "password": "Synthetic-result!2026"})
        assert login.status_code == 200, login.text
        created = client.post("/api/cases/1/results")
        assert created.status_code == 201, created.text
        url = created.headers["location"]
        assert client.get(url).status_code == 200
        latest = client.get("/api/cases/1/results/latest")
        assert latest.status_code == 200
        assert latest.json()["id"] == created.json()["id"]
        assert latest.headers["cache-control"] == "no-store"
        with factory() as db:
            db.execute(UserAreaScope.__table__.delete().where(UserAreaScope.user_id == user_id))
            db.commit()
        assert client.get(url).status_code == 404
        assert client.get("/api/cases/1/results/latest").status_code == 404
        assert client.get("/api/cases/1/results/history").status_code == 404
