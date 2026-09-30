"""Legacy knowledge adapters must distinguish inaccessible/unavailable from no match."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.api import knowledge
from app.database import get_db
from app.services.case_history_retrieval import HistoryUnavailable
from app.services.case_knowledge_service import CaseKnowledgeService
from app.services.knowledge_asset_service import KnowledgeAssetError, KnowledgeAssetService


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api/knowledge")

    @app.middleware("http")
    async def principal(request, call_next):
        request.state.principal = SimpleNamespace(user_id=1, role="analyst")
        return await call_next(request)

    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app) as result:
        yield result


@pytest.mark.parametrize("method,path,service,name,body", [
    ("GET", "/experience-cards", CaseKnowledgeService, "list_experience_cards", None),
    ("GET", "/experience-cards/search?q=软管", CaseKnowledgeService, "search_experience_cards", None),
    ("GET", "/cases/1/reuse-recommendations", KnowledgeAssetService, "reuse_recommendations", None),
    ("POST", "/cases/1/experience-assets", KnowledgeAssetService, "generate_experience_asset", None),
    ("POST", "/assets/1/review", KnowledgeAssetService, "review_asset", {"status": "confirmed"}),
])
@pytest.mark.parametrize("error,status", [(HistoryUnavailable, 404), (SQLAlchemyError, 503)])
def test_adapter_failure_is_not_an_empty_success(client, monkeypatch, method, path, service, name, body, error, status):
    def unavailable(*args, **kwargs):
        raise error("sensitive-internal-detail")

    monkeypatch.setattr(service, name, unavailable)
    response = client.request(method, "/api/knowledge" + path, json=body)
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert "sensitive-internal-detail" not in response.text
    if status == 503:
        assert "不能据此判断" in response.json()["detail"]


@pytest.mark.parametrize("code,text", [
    ("frozen_result_unavailable", "没有可访问的冻结案件成果"),
    ("frozen_result_stale", "冻结成果已过期"),
])
def test_report_awaits_frozen_result_instead_of_reanalysis(client, monkeypatch, code, text):
    def unavailable(*args, **kwargs):
        raise KnowledgeAssetError(code)

    monkeypatch.setattr(KnowledgeAssetService, "generate_report_snapshot", unavailable)
    result = client.post("/api/knowledge/cases/1/report-snapshots", json={})
    assert result.status_code == 409
    assert text in result.json()["detail"]


def test_public_experience_search_stays_bounded(client):
    assert client.get("/api/knowledge/experience-cards/search?q=油品&limit=21").status_code == 422
    assert client.get("/api/knowledge/experience-cards?status=invalid").status_code == 422


def test_legacy_case_only_review_requires_exact_current_asset_version(client, monkeypatch):
    def require_version(*args, **kwargs):
        raise ValueError("experience_asset_version_required")
    monkeypatch.setattr(CaseKnowledgeService, "update_experience_card_status", require_version)
    response = client.post("/api/knowledge/experience-cards/1/status", json={"status": "confirmed"})
    assert response.status_code == 409
    assert "具体资产版本" in response.json()["detail"]
