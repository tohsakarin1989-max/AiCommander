from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import agents, cases, conclusions, events, graphs, patrols, suggestions
from app.database import Base
from app.database import get_db
from app.models.case import CasePerson, CaseVehicle
from app.models.conclusion import Conclusion
from app.models.event import Event
from app.models.patrol import AreaRiskAssessment, PatrolRecord
from app.services.case_service import CaseService


@pytest.fixture
def api_db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_local()
    try:
        yield session
    finally:
        session.close()


def _build_client(db_session: Session) -> TestClient:
    app = FastAPI()
    app.include_router(cases.router, prefix="/api/cases", tags=["cases"])
    app.include_router(conclusions.router, prefix="/api/conclusions", tags=["conclusions"])
    app.include_router(events.router, prefix="/api/events", tags=["events"])
    app.include_router(patrols.router, prefix="/api/patrols", tags=["patrols"])
    app.include_router(graphs.router, prefix="/api/graphs", tags=["graphs"])
    app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
    app.include_router(suggestions.router, prefix="/api/suggestions", tags=["suggestions"])

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _add_event(
    db_session: Session,
    event_number: str,
    village_name: str = "测试村",
    event_type: str = "suspect_activity",
    days_ago: int = 1,
    latitude: float = 39.9,
    longitude: float = 116.4,
    vehicles: list[dict] | None = None,
) -> Event:
    event = Event(
        event_number=event_number,
        event_type=event_type,
        occurred_time=datetime.now() - timedelta(days=days_ago),
        location=f"{village_name}井场",
        latitude=latitude,
        longitude=longitude,
        village_name=village_name,
        title="接口契约测试事件",
        vehicles=vehicles,
    )
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)
    return event


def test_generate_conclusion_accepts_json_body(api_db_session: Session):
    client = _build_client(api_db_session)
    case = CaseService.create_case(
        db=api_db_session,
        case_number=None,
        occurred_time=datetime(2025, 1, 1, 10, 0, 0),
        description="用于接口契约测试的案件",
    )

    response = client.post("/api/conclusions/generate", json={"case_id": case.id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == case.id
    assert payload["status"] in {"published", "needs_review"}
    assert payload["evidence"]["raw"]["case_intelligence"]["experience_card"]["case_id"] == case.id


def test_case_create_accepts_initial_vehicle_and_person_drafts(api_db_session: Session):
    client = _build_client(api_db_session)

    response = client.post(
        "/api/cases/",
        json={
            "occurred_time": "2026-06-05T01:00:00",
            "description": "现场查扣涉案车辆并抓获涉案人员。",
            "initial_vehicles": [
                {
                    "vehicle_type": "5吨以下机动车",
                    "plate_number": "黑E12345",
                    "handling_status": "扣押停放",
                }
            ],
            "initial_persons": [
                {
                    "name": "张某",
                    "role": "司机",
                    "handling_status": "行政拘留",
                }
            ],
        },
    )

    assert response.status_code == 200
    case_id = response.json()["id"]
    vehicle = api_db_session.query(CaseVehicle).filter(CaseVehicle.case_id == case_id).one()
    person = api_db_session.query(CasePerson).filter(CasePerson.case_id == case_id).one()
    assert vehicle.vehicle_type == "5吨以下机动车"
    assert vehicle.plate_number == "黑E12345"
    assert person.name == "张某"
    assert person.handling_status == "行政拘留"


def test_case_update_replaces_bonus_drafts_and_clears_nullable_fields(api_db_session: Session):
    client = _build_client(api_db_session)
    case = CaseService.create_case(
        db=api_db_session,
        case_number=None,
        occurred_time=datetime(2026, 6, 5, 1, 0, 0),
        description="用于编辑清空合同测试的案件",
        oil_nature="被盗原油",
        oil_volume=2.5,
        water_cut=12.0,
        oil_handling="检斤入库",
        police_reported=True,
        case_filed=True,
        police_officer="张警官",
        police_phone="00000000000",
        initial_vehicles=[{"vehicle_type": "5吨以下机动车", "plate_number": "黑E12345"}],
        initial_persons=[{"name": "张某", "handling_status": "行政拘留"}],
    )
    vehicle = api_db_session.query(CaseVehicle).filter(CaseVehicle.case_id == case.id).one()

    response = client.put(
        f"/api/cases/{case.id}",
        json={
            "oil_nature": None,
            "oil_volume": None,
            "water_cut": None,
            "oil_handling": None,
            "police_reported": False,
            "case_filed": False,
            "police_officer": None,
            "police_phone": None,
            "initial_vehicles": [
                {
                    "id": vehicle.id,
                    "vehicle_type": "重型挂车",
                    "plate_number": None,
                    "handling_status": "移交公安",
                }
            ],
            "initial_persons": [],
        },
    )

    assert response.status_code == 200
    api_db_session.refresh(case)
    assert case.oil_nature is None
    assert case.oil_volume is None
    assert case.water_cut is None
    assert case.oil_handling is None
    assert case.police_reported is False
    assert case.case_filed is False
    assert case.police_officer is None
    assert case.police_phone is None

    vehicles = api_db_session.query(CaseVehicle).filter(CaseVehicle.case_id == case.id).all()
    persons = api_db_session.query(CasePerson).filter(CasePerson.case_id == case.id).all()
    assert len(vehicles) == 1
    assert vehicles[0].id == vehicle.id
    assert vehicles[0].vehicle_type == "重型挂车"
    assert vehicles[0].plate_number is None
    assert vehicles[0].handling_status == "移交公安"
    assert persons == []


def test_case_update_rejects_required_nulls_and_ignores_null_bonus_drafts(api_db_session: Session):
    client = _build_client(api_db_session)
    case = CaseService.create_case(
        db=api_db_session,
        case_number=None,
        occurred_time=datetime(2026, 6, 5, 1, 0, 0),
        description="用于空值边界测试的案件",
        initial_vehicles=[{"vehicle_type": "5吨以下机动车", "plate_number": "黑E12345"}],
    )

    required_null = client.put(f"/api/cases/{case.id}", json={"occurred_time": None})
    assert required_null.status_code == 422

    draft_null = client.put(f"/api/cases/{case.id}", json={"initial_vehicles": None})
    assert draft_null.status_code == 200
    vehicles = api_db_session.query(CaseVehicle).filter(CaseVehicle.case_id == case.id).all()
    assert len(vehicles) == 1
    assert vehicles[0].plate_number == "黑E12345"


def test_review_conclusion_accepts_json_body(api_db_session: Session):
    client = _build_client(api_db_session)
    conclusion = Conclusion(
        case_id=1,
        status="needs_review",
        confidence=0.6,
        risk_level="medium",
        summary="待审核结论",
        evidence={},
    )
    api_db_session.add(conclusion)
    api_db_session.commit()
    api_db_session.refresh(conclusion)

    response = client.post(
        f"/api/conclusions/{conclusion.id}/review",
        json={"action": "approve"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "published"
    assert payload["review_action"] == "approve"


def test_hotspot_evolution_route_is_reachable(api_db_session: Session):
    client = _build_client(api_db_session)

    response = client.get("/api/cases/hotspot-evolution")

    assert response.status_code == 200
    payload = response.json()
    assert "periods" in payload
    assert "trend_summary" in payload


def test_event_static_routes_are_reachable(api_db_session: Session):
    client = _build_client(api_db_session)

    areas = client.get("/api/events/areas")
    risk_ranking = client.get("/api/events/area/risk-ranking")
    hotspots = client.get("/api/events/area/hotspots")
    stats = client.get("/api/events/statistics")
    map_data = client.get("/api/events/map-data")

    assert areas.status_code == 200
    assert risk_ranking.status_code == 200
    assert hotspots.status_code == 200
    assert stats.status_code == 200
    assert map_data.status_code == 200


def test_event_area_analyze_serializes_service_models(api_db_session: Session):
    client = _build_client(api_db_session)
    event = _add_event(
        api_db_session,
        event_number="EVT-AREA-001",
        village_name="分析村",
        event_type="stash_found",
    )

    response = client.post(
        "/api/events/area/analyze",
        json={"area_name": "分析村", "radius_km": 5, "days_back": 30},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["area_name"] == "分析村"
    assert payload["events"][0]["id"] == event.id
    assert payload["events"][0]["event_number"] == event.event_number


def test_event_area_risk_ranking_route_uses_service(api_db_session: Session):
    client = _build_client(api_db_session)
    _add_event(
        api_db_session,
        event_number="EVT-RISK-001",
        village_name="高风险村",
        event_type="pipeline_tap",
    )

    response = client.get("/api/events/area/risk-ranking")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["area_name"] == "高风险村"
    assert payload[0]["risk_score"] > 0


def test_event_hotspots_route_identifies_recent_area(api_db_session: Session):
    client = _build_client(api_db_session)
    _add_event(api_db_session, event_number="EVT-HOT-001", village_name="热点村")
    _add_event(
        api_db_session,
        event_number="EVT-HOT-002",
        village_name="热点村",
        latitude=39.901,
        longitude=116.401,
    )

    response = client.get("/api/events/area/hotspots?days_back=30&min_events=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["area_name"] == "热点村"
    assert payload[0]["event_count"] == 2


def test_refresh_area_profile_handles_model_events(api_db_session: Session):
    client = _build_client(api_db_session)
    _add_event(
        api_db_session,
        event_number="EVT-PROFILE-001",
        village_name="档案村",
        event_type="stash_found",
        latitude=39.9,
        longitude=116.4,
    )
    _add_event(
        api_db_session,
        event_number="EVT-PROFILE-002",
        village_name="档案村",
        event_type="vehicle_caught",
        days_ago=20,
        latitude=39.902,
        longitude=116.402,
    )

    response = client.post("/api/events/areas/档案村/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["area_name"] == "档案村"
    assert payload["total_events"] == 2
    assert payload["risk_score"] > 0


def test_event_correlations_analyze_normalizes_event_id_shape(api_db_session: Session):
    client = _build_client(api_db_session)
    event_a = _add_event(
        api_db_session,
        event_number="EVT-CORR-001",
        village_name="关联村",
        event_type="suspect_activity",
        latitude=39.9,
        longitude=116.4,
    )
    event_b = _add_event(
        api_db_session,
        event_number="EVT-CORR-002",
        village_name="关联村",
        event_type="suspect_activity",
        latitude=39.901,
        longitude=116.401,
    )

    response = client.post(
        "/api/events/correlations/analyze",
        json={"event_ids": [event_a.id, event_b.id]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["relation_count"] >= 1
    relation = payload["relations"][0]
    assert {relation["event_a_id"], relation["event_b_id"]} == {event_a.id, event_b.id}
    assert relation["relation_type"] == "spatial_cluster"
    assert "event" not in relation


def test_create_event_generates_incrementing_numbers(api_db_session: Session):
    client = _build_client(api_db_session)
    request_body = {
        "event_type": "suspect_activity",
        "occurred_time": "2026-04-25T10:00:00",
        "title": "夜间异常车辆活动",
        "description": "巡逻发现井场附近有车辆停留。",
        "location": "测试井场",
    }

    first = client.post("/api/events/", json=request_body)
    second = client.post("/api/events/", json=request_body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["event_number"] != second.json()["event_number"]


def test_patrol_static_routes_are_reachable(api_db_session: Session):
    client = _build_client(api_db_session)

    risks = client.get("/api/patrols/areas/risks")
    schedule = client.get("/api/patrols/smart-schedule")

    assert risks.status_code == 200
    assert schedule.status_code == 200
    assert "recommended_windows" in schedule.json()


def test_graph_serial_accepts_frontend_request_shape(api_db_session: Session):
    client = _build_client(api_db_session)
    case = CaseService.create_case(
        db=api_db_session,
        case_number=None,
        occurred_time=datetime(2025, 1, 1, 10, 0, 0),
        description="用于图谱契约测试的案件",
    )

    response = client.post("/api/graphs/serial", json={"case_ids": [case.id]})

    assert response.status_code == 200
    assert "nodes" in response.json()


def test_agent_run_accepts_frontend_request_shape(api_db_session: Session):
    client = _build_client(api_db_session)

    response = client.post("/api/agents/run", json={"query": "研判最近案件"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "研判最近案件"
    assert payload["result"]["steps"]
    assert "facts" in payload["result"]
    assert "自动侦查" not in payload["result"]["result"]


def test_suggestions_route_returns_queue_shape(api_db_session: Session):
    client = _build_client(api_db_session)

    response = client.get("/api/suggestions/")

    assert response.status_code == 200
    payload = response.json()
    assert "suggestions" in payload
    assert "total" in payload
    assert "generated_at" in payload


def test_suggestions_expose_area_reference_without_patrol_execution_task(api_db_session: Session):
    client = _build_client(api_db_session)
    api_db_session.add(
        AreaRiskAssessment(
            area_name="高风险测试区",
            risk_score=82,
            risk_level="high",
            case_count_30d=5,
        )
    )
    api_db_session.commit()

    before = client.get("/api/suggestions/").json()["suggestions"]
    assert any(
        item["id"].startswith("area-reference-")
        and item["action"] == "review_prevention_reference"
        for item in before
    )
    assert not any(item["id"].startswith("area-patrol-") for item in before)

    api_db_session.add(
        PatrolRecord(
            patrol_number="PTEST001",
            area_name="高风险测试区",
            patrol_type="targeted",
            status="planned",
        )
    )
    api_db_session.commit()

    after = client.get("/api/suggestions/").json()["suggestions"]
    assert any(item["id"].startswith("area-reference-") for item in after)
    assert not any(item["id"].startswith("area-patrol-") for item in after)


def test_event_convert_to_case_accepts_frontend_action(api_db_session: Session):
    client = _build_client(api_db_session)

    created = client.post(
        "/api/events/",
        json={
            "event_type": "suspect_activity",
            "occurred_time": "2026-04-25T10:00:00",
            "title": "夜间异常车辆活动",
            "description": "巡逻发现井场附近有车辆停留。",
            "location": "测试井场",
        },
    )
    assert created.status_code == 200
    event_id = created.json()["id"]

    converted = client.post(f"/api/events/{event_id}/convert-to-case")

    assert converted.status_code == 200
    payload = converted.json()
    assert payload["event_id"] == event_id
    assert isinstance(payload["case_id"], int)

    event_after = client.get(f"/api/events/{event_id}").json()
    assert event_after["related_case_id"] == payload["case_id"]
