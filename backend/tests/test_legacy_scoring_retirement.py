"""Retired scoring cannot execute; independent facts and history remain readable."""
from copy import deepcopy
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import case_intelligence, deployment, events, jurisdiction
from app.database import Base, get_db
from app.models.case import Case
from app.models.event import AreaProfile
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.jurisdiction_service import JurisdictionService


def _client():
    app = FastAPI()
    app.include_router(case_intelligence.router, prefix="/api/case-intelligence")
    app.include_router(deployment.router, prefix="/api/deployment")
    app.include_router(events.router, prefix="/api/events")
    app.include_router(jurisdiction.router, prefix="/api/jurisdiction")
    return app, TestClient(app)


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/api/case-intelligence/area-profiles", None),
    ("post", "/api/events/area/analyze", {"area_name": "合成区域"}),
    ("get", "/api/events/area/risk-ranking", None),
    ("get", "/api/events/area/hotspots", None),
    ("post", "/api/events/areas/合成区域/refresh", None),
    ("post", "/api/deployment/smart-analysis", None),
    ("get", "/api/jurisdiction/assets/1/risk-profile", None),
    ("get", "/api/jurisdiction/cases/1/risk-context", None),
    ("get", "/api/jurisdiction/cases/1/experience-card", None),
    ("get", "/api/jurisdiction/similar-targets?case_id=1", None),
    ("get", "/api/jurisdiction/roundtable-briefing?case_id=1", None),
    ("get", "/api/jurisdiction/prevention-workbench?case_id=1", None),
    ("post", "/api/jurisdiction/patrol-plan", {"case_id": 1}),
    ("post", "/api/jurisdiction/patrol-plan/materialize", {"case_id": 1}),
])
def test_retired_routes_never_open_database_or_run_analysis(method, path, payload, monkeypatch):
    app, client = _client()

    def forbidden(*args, **kwargs):
        raise AssertionError("retired scoring must not access DB or execute a service")

    app.dependency_overrides[get_db] = forbidden
    from app.services.area_analysis_service import AreaAnalysisService
    from app.services.smart_analysis_service import SmartAnalysisService
    monkeypatch.setattr(AreaAnalysisService, "analyze_area", forbidden)
    monkeypatch.setattr(SmartAnalysisService, "analyze", forbidden)
    response = client.request(method, path, **({"json": payload} if payload else {}))
    assert response.status_code == 404
    assert path.split('?')[0] not in app.openapi()['paths']


def test_historical_area_profiles_are_readable_and_not_rewritten():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["authorized_area_ids"] = None
        profile = AreaProfile(area_name="合成历史档案", risk_score=81, risk_level="high",
                              total_events=3, assessment="历史人工记录", boundary={"type": "Polygon"})
        db.add(profile)
        db.commit()
        before = deepcopy({column.name: getattr(profile, column.name) for column in profile.__table__.columns})
        app, client = _client()
        def fixture_db():
            yield db
        app.dependency_overrides[get_db] = fixture_db
        assert client.get("/api/events/areas").status_code == 200
        assert client.get(f"/api/events/areas/{profile.id}").json()["assessment"] == "历史人工记录"
        assert client.post("/api/events/areas/合成历史档案/refresh").status_code == 404
        db.refresh(profile)
        assert {column.name: getattr(profile, column.name) for column in profile.__table__.columns} == before
        assert db.query(AreaProfile).count() == 1


def test_case_geography_does_not_compute_legacy_risk(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy risk context is retired")
    monkeypatch.setattr(JurisdictionService, "build_case_risk_context", forbidden)
    monkeypatch.setattr(JurisdictionService, "_nearest_asset", lambda *args: None)
    case = Case(id=1, case_number="SYN-GEO", occurred_time=datetime.now(), latitude=45, longitude=124)
    context = CaseIntelligenceService._safe_case_context(None, case)
    assert context["state"] == "ready"
    assert context["risk_score"] is None and context["risk_conditions"] == []
    assert "不代表道路通达" in context["boundary"]
    monkeypatch.setattr(JurisdictionService, "_nearest_asset", forbidden)
    unavailable = CaseIntelligenceService._safe_case_context(None, case)
    assert unavailable["state"] == "unavailable" and unavailable["risk_score"] is None
    case.latitude = None
    assert CaseIntelligenceService._safe_case_context(None, case)["state"] == "missing_coordinates"


def test_case_count_does_not_become_a_risk_score():
    from app.services.gang_analysis_service import GangAnalysisService
    features = [GangAnalysisService.extract_case_features(Case(id=i, case_number=f'SYN-{i}'))
                for i in range(1, 10)]
    result = GangAnalysisService._generate_gang_profile(features)
    assert result['risk_score'] is None
    assert result['risk_score_status'] == 'retired'


def test_context_discards_old_area_scores_and_keeps_partial_retrieval_boundary():
    payload = {"area_profiles": {"items": [{"name": "旧评分区域", "risk_score": 99, "risk_level": "high"}]},
               "similar_cases": {"state": "partial", "items": [], "coverage": {"complete": False}}}
    context = CaseIntelligenceService._build_llm_context_from_workbench(payload)
    assert "旧评分区域" not in str(context)
    assert "未计算不表示零风险" in str(context)
    assert "历史检索未覆盖完整范围" in str(context)
    assert not any(item.get("kind") == "area_profile" for item in context["evidence_index"])


def test_legacy_history_failure_is_explicit_not_empty_matches(monkeypatch):
    app, client = _client()
    app.dependency_overrides[get_db] = lambda: None
    def failed(*args, **kwargs):
        raise OperationalError("test", {}, Exception("private db failure"))
    monkeypatch.setattr(CaseIntelligenceService, "find_similar_cases", failed)
    response = client.get("/api/case-intelligence/cases/1/similar")
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert "不能据此判断没有匹配" in response.json()["detail"]
    assert "private" not in response.text
