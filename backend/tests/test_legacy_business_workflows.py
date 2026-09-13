"""保留的 v1/v2 基础业务通过真实 HTTP、服务与隔离数据库串联验证。"""
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import cases, deployment, events, gangs, key_locations, patrols, personnel
from app.config import settings
from app.database import Base, get_db
from app.models.case import Case
from app.models.map_foundation import OperationalArea
from app.models.patrol import AreaRiskAssessment


@pytest.fixture
def legacy_business(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.add(OperationalArea(id=1, code="LEGACY-BIZ", name="合成业务辖区"))
        db.commit()
    monkeypatch.setattr(settings, "ENABLE_VECTOR_DB", False)
    monkeypatch.setattr(settings, "ENABLE_LEGACY_EXTERNAL_GEO", False)
    app = FastAPI()
    for module, prefix in ((cases, "cases"), (events, "events"), (gangs, "gangs"),
                           (deployment, "deployment"),
                           (personnel, "personnel"), (key_locations, "key-locations"), (patrols, "patrols")):
        app.include_router(module.router, prefix=f"/api/{prefix}")

    def database():
        with factory() as db:
            db.info.update(authorized_area_ids=(1,), area_access_levels={1: "write"},
                           default_operational_area_id=1)
            yield db

    app.dependency_overrides[get_db] = database
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, factory
    engine.dispose()


def post_case(client, **overrides):
    payload = {"occurred_time": datetime.now().replace(hour=2).isoformat(),
               "location": "合成井场", "latitude": 45.0, "longitude": 124.0,
               "description": "合成已处置案件：夜间井场发现软管，现场照明不足。",
               "case_type": "涉油案件", "modus_operandi": "夜间使用软管盗油",
               "facility_type": "油井", "source_type": "巡逻发现", "oil_type": "原油"}
    response = client.post("/api/cases/", json={**payload, **overrides})
    assert response.status_code == 200, response.text
    return response.json()


def test_case_crud_number_statistics_and_persisted_condition_group(legacy_business):
    client, factory = legacy_business
    first = post_case(client)
    second = post_case(client, longitude=124.001)
    assert first["case_number"] != second["case_number"]
    assert second["case_number"].endswith("002")
    stats = client.get("/api/cases/statistics").json()
    assert stats["total_cases"] == 2
    assert stats["pending_cases"] == 2
    assert stats["cases_with_geo"] == 2
    updated = client.put(f"/api/cases/{first['id']}", json={"status": "resolved", "location": "合成井场东侧"})
    assert updated.status_code == 200, updated.text
    assert client.get(f"/api/cases/{first['id']}").json()["location"] == "合成井场东侧"
    assert client.get("/api/cases/statistics").json()["resolved_cases"] == 1
    clustered = client.post("/api/gangs/identify", json={"case_ids": [first["id"], second["id"]]})
    assert clustered.status_code == 200, clustered.text
    assert len(clustered.json()) == 1
    assert set(clustered.json()[0]["case_ids"]) == {first["id"], second["id"]}
    assert client.get("/api/gangs/quick-identify").json()["total_gangs"] == 1
    assert client.get("/api/gangs/0/relations").status_code == 200
    timeline = client.post("/api/gangs/timeline", json=[first["id"], second["id"]])
    assert timeline.status_code == 200, timeline.text
    assert {item["case_id"] for item in timeline.json()} == {first["id"], second["id"]}
    assert client.get("/api/gangs/statistics").status_code == 200
    assert client.delete(f"/api/cases/{second['id']}").status_code == 200
    assert client.get(f"/api/cases/{second['id']}").status_code == 404
    assert client.get("/api/cases/statistics").json()["total_cases"] == 1
    with factory() as db:
        assert db.query(Case).count() == 1


def test_event_crud_conversion_is_idempotent_and_preserves_source_facts(legacy_business):
    client, factory = legacy_business
    created = client.post("/api/events/", json={
        "event_type": "suspect_activity", "occurred_time": datetime.now().isoformat(),
        "location": "合成事件井场", "latitude": 45, "longitude": 124,
        "title": "合成可疑活动", "description": "发现遗留软管", "equipment": ["软管"],
        "discovery_method": "现场发现", "oil_type": "原油", "oil_volume_liters": 10,
    })
    assert created.status_code == 200, created.text
    event_id = created.json()["id"]
    assert client.get(f"/api/events/{event_id}").json()["equipment"] == ["软管"]
    updated = client.put(f"/api/events/{event_id}", json={"handling_result": "已核实", "review_status": "confirmed"})
    assert updated.status_code == 200, updated.text
    converted = client.post(f"/api/events/{event_id}/convert-to-case")
    assert converted.status_code == 200, converted.text
    case_id = converted.json()["case_id"]
    assert client.post(f"/api/events/{event_id}/convert-to-case").json()["case_id"] == case_id
    case = client.get(f"/api/cases/{case_id}").json()
    assert case["operational_area_id"] == 1
    assert case["location"] == "合成事件井场"
    assert "已核实" in case["description"] and "软管" in case["description"]
    assert case["oil_volume"] is None  # 升不能直接填入按吨使用的案件字段。
    assert "10升" in case["description"] and "吨数待核定" in case["description"]
    assert client.get(f"/api/events/{event_id}").json()["oil_volume_liters"] == 10
    with factory() as db:
        assert db.query(Case).count() == 1
    assert client.get("/api/events/statistics").status_code == 200
    assert client.get("/api/events/map-data").status_code == 200
    assert client.delete(f"/api/events/{event_id}").status_code == 200
    assert client.get(f"/api/events/{event_id}").status_code == 404
    assert client.get(f"/api/cases/{case_id}").status_code == 200


@pytest.mark.parametrize("path,payload,updated,query", [
    ("personnel", {"name": "合成人员", "badge_number": "SYN-001", "department": "合成班组"},
     {"department": "合成新班组"}, "department=合成新班组"),
    ("key-locations", {"name": "合成重点井场", "location_type": "well", "latitude": 45, "longitude": 124},
     {"risk_level": 3}, "location_type=well"),
])
def test_legacy_reference_registry_lifecycle(legacy_business, path, payload, updated, query):
    client, _ = legacy_business
    created = client.post(f"/api/{path}", json=payload)
    assert created.status_code == 200, created.text
    item_id = created.json()["id"]
    response = client.put(f"/api/{path}/{item_id}", json=updated)
    assert response.status_code == 200, response.text
    assert all(response.json()[key] == value for key, value in updated.items())
    assert [item["id"] for item in client.get(f"/api/{path}?{query}").json()] == [item_id]
    assert client.delete(f"/api/{path}/{item_id}").status_code == 200
    assert client.get(f"/api/{path}").json() == []
    assert client.put(f"/api/{path}/{item_id}", json=updated).status_code == 404


def test_legacy_patrol_plan_start_complete_updates_risk_and_history(legacy_business):
    client, factory = legacy_business
    created = client.post("/api/patrols/", json={"area_name": "合成井场", "officer_names": "合成人员"})
    assert created.status_code == 200, created.text
    patrol_id = created.json()["id"]
    assert created.json()["status"] == "planned"
    assert created.json()["patrol_number"].startswith("XL-")
    started = client.post(f"/api/patrols/{patrol_id}/start")
    assert started.status_code == 200 and started.json()["start_time"]
    completed = client.post(f"/api/patrols/{patrol_id}/complete", json={
        "findings": "合成检查已完成", "effectiveness_score": 0, "evidence_photos": ["synthetic-photo"],
    })
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert completed.json()["end_time"]
    assert completed.json()["effectiveness_score"] == 0
    assert completed.json()["risk_after"] == 45  # 无案件基础风险40，低效果评分加5。
    assert len(client.get("/api/patrols/?status=completed").json()) == 1
    with factory() as db:
        risk = db.query(AreaRiskAssessment).one()
        assert risk.risk_score == 45 and risk.risk_level == "medium"
        assert risk.patrol_count_30d == 1
        assert "评分：0" in risk.risk_history[-1]["reason"]
    assert client.get("/api/patrols/areas/risks").status_code == 200


def test_legacy_patrol_effectiveness_adjustment_updates_risk_level(legacy_business):
    client, factory = legacy_business
    patrol_id = client.post("/api/patrols/", json={"area_name": "合成降险井场"}).json()["id"]
    assert client.post(f"/api/patrols/{patrol_id}/start").status_code == 200
    response = client.post(f"/api/patrols/{patrol_id}/complete", json={"effectiveness_score": 90})
    assert response.status_code == 200, response.text
    assert response.json()["risk_after"] == 35
    with factory() as db:
        assert db.query(AreaRiskAssessment).one().risk_level == "low"


@pytest.mark.parametrize("terminal,action", [("cancelled", "start"), ("cancelled", "complete"),
                                              ("completed", "start"), ("completed", "cancel")])
def test_legacy_patrol_terminal_state_cannot_be_rewritten(legacy_business, terminal, action):
    client, _ = legacy_business
    patrol_id = client.post("/api/patrols/", json={"area_name": "合成终态井场"}).json()["id"]
    if terminal == "cancelled":
        assert client.post(f"/api/patrols/{patrol_id}/cancel").status_code == 200
    else:
        assert client.post(f"/api/patrols/{patrol_id}/start").status_code == 200
        assert client.post(f"/api/patrols/{patrol_id}/complete", json={}).status_code == 200
    response = client.post(f"/api/patrols/{patrol_id}/{action}", json={})
    assert response.status_code == 409, response.text
    assert client.get(f"/api/patrols/{patrol_id}").json()["status"] == terminal


def test_event_area_analysis_to_persisted_relation_and_human_confirmation(legacy_business):
    client, _ = legacy_business
    event_ids = []
    for index in range(2):
        response = client.post("/api/events/", json={
            "event_type": "suspect_activity", "occurred_time": datetime.now().isoformat(),
            "location": "合成关联井场", "village_name": "合成关联村",
            "latitude": 45, "longitude": 124 + index * 0.001,
            "vehicles": [{"plate": "SYN-VEHICLE"}],
        })
        assert response.status_code == 200, response.text
        event_ids.append(response.json()["id"])
    area = client.post("/api/events/area/analyze", json={"area_name": "合成关联村"})
    assert area.status_code == 200, area.text
    assert len(area.json()["events"]) == 2
    assert area.json()["risk_assessment"]
    assert client.get("/api/events/area/risk-ranking").status_code == 200
    assert client.post("/api/events/areas/合成关联村/refresh").status_code == 200
    analysis = client.post("/api/events/correlations/analyze", json={"event_ids": event_ids})
    assert analysis.status_code == 200, analysis.text
    assert {item["relation_type"] for item in analysis.json()["relations"]} == {"spatial_cluster", "vehicle_link"}
    persisted = client.get("/api/events/correlations").json()
    assert len(persisted) == analysis.json()["relation_count"]
    relation_id = persisted[0]["id"]
    assert client.post(f"/api/events/correlations/{relation_id}/confirm?confirmed=true&confirmed_by=合成复核员").json()["is_confirmed"]
    client.post("/api/events/correlations/analyze", json={"event_ids": event_ids})
    assert len(client.get("/api/events/correlations").json()) == len(persisted)
    assert client.get("/api/events/correlations?is_confirmed=true").json()[0]["id"] == relation_id
    assert client.post(f"/api/events/correlations/{relation_id}/confirm?confirmed=false").status_code == 200
    assert client.get("/api/events/correlations?is_confirmed=true").json() == []


def test_legacy_deployment_suggestions_derive_from_case_records(legacy_business):
    client, _ = legacy_business
    post_case(client)
    post_case(client, longitude=124.001, occurred_time=(datetime.now() - timedelta(days=1)).replace(hour=2).isoformat())
    report = client.get("/api/deployment/report")
    assert report.status_code == 200, report.text
    assert report.json()["temporal_analysis"]["total_cases"] == 2
    for endpoint in ("temporal-patterns", "target-patterns", "patrol-routes", "resource-allocation", "prevention-measures"):
        response = client.get(f"/api/deployment/{endpoint}")
        assert response.status_code == 200, (endpoint, response.text)
        assert response.json()


@pytest.mark.parametrize("description,expected", [
    ("现场发现原油10升，吨数待核定", None),
    ("现场发现原油10L，吨数待核定", None),
    ("检斤核定原油10吨", 10.0),
    ("检斤核定原油500公斤", 0.5),
    ("现场估计10升，检斤核定原油0.008吨", 0.008),
])
def test_oil_structure_extraction_never_assumes_liters_equal_tons(description, expected):
    from app.services.case_automation_service import CaseAutomationService

    assert CaseAutomationService._extract_volume_tons(description) == expected


@pytest.mark.parametrize("inferred_tons", [10, 0.01])
def test_model_intake_cannot_reintroduce_unverified_oil_mass(inferred_tons):
    import json
    from types import SimpleNamespace
    from app.services.case_automation_service import CaseAutomationService

    class IncorrectModel:
        def invoke(self, prompt):
            return SimpleNamespace(content=json.dumps({
                "case_fields": {"oil_volume": inferred_tons, "description": f"原油{inferred_tons}吨"},
                "candidates": [{"field": "oil_volume", "value": inferred_tons, "label": "油量"}],
            }))

    result = CaseAutomationService.structure_case_text("现场发现原油10升，尚未检斤", llm=IncorrectModel())
    assert result["case_fields"].get("oil_volume") is None
    assert "10升" in result["case_fields"]["description"]
    assert all(item["field"] != "oil_volume" for item in result["candidates"])
