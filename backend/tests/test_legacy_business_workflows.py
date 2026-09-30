"""保留的 v1/v2 基础业务通过真实 HTTP、服务与隔离数据库串联验证。"""
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import cases, deployment, events
from app.config import settings
from app.database import Base, get_db
from app.models.case import Case
from app.models.map_foundation import OperationalArea
from copy import deepcopy
from app.models.patrol import PatrolRecord
from app.models.personnel import SecurityPersonnel
from app.models.key_location import KeyLocation


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
    for module, prefix in ((cases, "cases"), (events, "events"), (deployment, "deployment")):
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


def test_case_crud_number_statistics_survive_group_retirement(legacy_business):
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
    assert client.post("/api/gangs/identify", json={"case_ids": [first["id"], second["id"]]}).status_code == 404
    assert client.get("/api/gangs/statistics").status_code == 404
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
    assert case["oil_volume"] == 10
    assert case["oil_volume_unit"] == "liter"  # 保存原始体积，不冒充吨数。
    assert "10升" in case["description"] and "吨数待核定" in case["description"]
    assert client.get(f"/api/events/{event_id}").json()["oil_volume_liters"] == 10
    with factory() as db:
        assert db.query(Case).count() == 1
    assert client.get("/api/events/statistics").status_code == 200
    assert client.get("/api/events/map-data").status_code == 200
    assert client.delete(f"/api/events/{event_id}").status_code == 200
    assert client.get(f"/api/events/{event_id}").status_code == 404
    assert client.get(f"/api/cases/{case_id}").status_code == 200


@pytest.mark.parametrize("path,model,payload", [
    ("personnel", SecurityPersonnel, {"name": "合成人员", "badge_number": "SYN-001"}),
    ("key-locations", KeyLocation, {"name": "合成旧重点部位", "location_type": "well"}),
    ("patrols", PatrolRecord, {"patrol_number": "SYN-001", "area_name": "合成历史区域",
                              "status": "completed", "findings": "保留历史人工记录"}),
])
def test_retired_operations_have_no_runtime_routes_and_preserve_history(legacy_business, path, model, payload):
    client, factory = legacy_business
    with factory() as db:
        record = model(**payload)
        db.add(record)
        db.commit()
        before = deepcopy({column.name: getattr(record, column.name) for column in model.__table__.columns})
        item_id = record.id
    for method, suffix in [("get", ""), ("post", ""), ("put", f"/{item_id}"),
                           ("delete", f"/{item_id}"), ("post", f"/{item_id}/start")]:
        response = client.request(method, f"/api/{path}{suffix}", json=payload)
        assert response.status_code == 404
    with factory() as db:
        record = db.query(model).one()
        assert {column.name: getattr(record, column.name) for column in model.__table__.columns} == before


def test_retired_area_scoring_preserves_event_relations_and_human_confirmation(legacy_business):
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
    assert area.status_code == 404, area.text
    assert client.get("/api/events/area/risk-ranking").status_code == 404
    assert client.post("/api/events/areas/合成关联村/refresh").status_code == 404
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
    assert result["case_fields"]["oil_volume"] == 10
    assert result["case_fields"]["oil_volume_unit"] == "liter"
    assert "10升" in result["case_fields"]["description"]
    quantities = [item for item in result["candidates"] if item["field"] == "oil_volume"]
    assert len(quantities) == 1 and quantities[0]["value"] == 10
