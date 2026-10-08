"""Real AuthMiddleware and the unchanged array-shaped facility search API."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app import database
from app.api import auth, jurisdiction
from app.models.map_foundation import UserAreaScope
from app.models.user import User
from app.security import AuthMiddleware
from app.services.auth_service import AuthService
from app.services.facility_search_service import FacilitySearchService
from tests.test_facility_search_v73 import asset, historical, seed_search


def test_real_api_search_contract_revocation_and_failure(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'synthetic-search.sqlite'}",
                           connect_args={"check_same_thread": False})
    database.Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    with sessions() as db:
        seed_search(db)
        user = db.query(User).filter_by(id=1).one()
        user.role = "analyst"
        user.password_hash = AuthService.hash_password("SyntheticSearchOnly123!")
        db.add(UserAreaScope(user_id=1, operational_area_id=1, access_level="read"))
        item = asset(db)
        historical(db, item, "早期旧名称")
        db.commit()
        item_id = item.id
    app = FastAPI()
    app.state.environment = "test"
    app.include_router(auth.router, prefix="/api/auth")
    app.include_router(jurisdiction.router, prefix="/api/jurisdiction")
    app.add_middleware(AuthMiddleware, session_factory=sessions, auth_required=True,
                       secure_cookie=False, allowed_origins=("http://testserver",))
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            path = "/api/jurisdiction/assets"
            assert client.get(path).status_code == 401
            assert client.post("/api/auth/login", json={"username": "synthetic-search",
                "password": "SyntheticSearchOnly123!"}).status_code == 200
            response = client.get(path, params={"keyword": "早期", "limit": 1})
            assert response.status_code == 200, response.text
            assert isinstance(response.json(), list)
            assert response.json()[0]["id"] == item_id
            assert response.json()[0]["name"] == "当前井名"
            assert response.json()[0]["search_match"]["kind"] == "historical_name"
            assert response.json()[0]["search_match"]["value"] == "早期旧名称"
            assert client.get(path, params={"keyword": "无结果"}).json() == []
            assert client.get(path, params={"skip": -1}).status_code == 422
            assert client.get(path, params={"limit": 1001}).status_code == 422
            with sessions() as db:
                db.query(UserAreaScope).filter_by(user_id=1).delete()
                db.commit()
            assert client.get(path, params={"keyword": "早期"}).json() == []

            def broken(*_args, **_kwargs):
                raise OperationalError("synthetic failure", {}, Exception("offline"))
            monkeypatch.setattr(FacilitySearchService, "filtered_query", broken)
            assert client.get(path).status_code == 500
    finally:
        engine.dispose()
