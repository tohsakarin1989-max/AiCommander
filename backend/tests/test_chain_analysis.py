from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import cases, chain_links
from app.database import Base, get_db
from app.models.case import Case
from app.models.chain_link import ChainLink
from app.services.chain_analysis_service import ChainAnalysisService
from app.utils.chain_classifier import classify_chain_position, get_chain_position_meta


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return session_local()


def _client(db_session: Session) -> TestClient:
    app = FastAPI()
    app.include_router(cases.router, prefix="/api/cases")
    app.include_router(chain_links.router, prefix="/api/chain-links")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _case(
    db: Session,
    number: str,
    facility_type: str,
    occurred_time: datetime,
    latitude: float,
    longitude: float,
) -> Case:
    item = Case(
        case_number=number,
        occurred_time=occurred_time,
        location=f"{facility_type}测试点",
        latitude=latitude,
        longitude=longitude,
        case_type="涉油盗窃",
        facility_type=facility_type,
        description=f"{facility_type}环节案件",
        status="pending",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def test_chain_classifier_maps_facility_types_without_database_field():
    assert classify_chain_position({"facility_type": "输油管线"}) == "upstream"
    assert classify_chain_position({"facility_type": "管线"}) == "upstream"
    assert classify_chain_position({"facility_type": "油罐车"}) == "midstream"
    assert classify_chain_position({"facility_type": "罐车抓获"}) == "midstream"
    assert classify_chain_position({"facility_type": "油库"}) == "downstream"
    assert classify_chain_position({"facility_type": "加油站"}) == "downstream"
    assert classify_chain_position({"facility_type": "其他"}) == "unknown"
    assert classify_chain_position({"facility_type": None}) == "unknown"

    meta = get_chain_position_meta("midstream")

    assert meta["label"] == "运输环节"
    assert meta["shape"] == "diamond"


def test_cases_filter_missing_location_and_patch_location():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(hours=1)

    created = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "未补坐标井场",
            "case_type": "涉油盗窃",
            "description": "历史案件缺少经纬度。",
            "facility_type": "管线",
        },
    )
    assert created.status_code == 200
    case_id = created.json()["id"]

    missing = client.get("/api/cases/", params={"missing_location": True})
    assert missing.status_code == 200
    assert [item["id"] for item in missing.json()] == [case_id]

    invalid = client.patch(f"/api/cases/{case_id}/location", json={"latitude": 54, "longitude": 125})
    assert invalid.status_code == 400

    patched = client.patch(f"/api/cases/{case_id}/location", json={"latitude": 46.5977, "longitude": 125.1034})
    assert patched.status_code == 200
    assert patched.json()["latitude"] == 46.5977
    assert patched.json()["longitude"] == 125.1034

    after = client.get("/api/cases/", params={"missing_location": True})
    assert after.status_code == 200
    assert after.json() == []


def test_chain_scan_creates_idempotent_upstream_and_downstream_links():
    db = _session()
    base_time = datetime(2026, 5, 1, 8, 0, 0)
    upstream = _case(db, "CHAIN-001", "管线", base_time, 46.6000, 125.1000)
    midstream = _case(db, "CHAIN-002", "油罐车", base_time + timedelta(days=4), 46.6200, 125.1200)
    downstream = _case(db, "CHAIN-003", "油库", base_time + timedelta(days=8), 46.6500, 125.1500)

    links = ChainAnalysisService.scan_chain_links(midstream.id, db)

    assert len(links) == 2
    by_type = {link.link_type: link for link in links}
    assert by_type["upstream_transport"].case_id_a == upstream.id
    assert by_type["upstream_transport"].case_id_b == midstream.id
    assert by_type["transport_storage"].case_id_a == midstream.id
    assert by_type["transport_storage"].case_id_b == downstream.id
    assert all(link.status == "inferred" for link in links)
    assert all(0.3 <= link.confidence <= 1 for link in links)

    second = ChainAnalysisService.scan_chain_links(midstream.id, db)

    assert {link.id for link in second} == {link.id for link in links}
    assert db.query(ChainLink).count() == 2


def test_chain_api_confirm_reject_and_map_data():
    db = _session()
    client = _client(db)
    base_time = datetime(2026, 5, 1, 8, 0, 0)
    upstream = _case(db, "CHAIN-API-001", "管线", base_time, 46.6000, 125.1000)
    midstream = _case(db, "CHAIN-API-002", "油罐车", base_time + timedelta(days=2), 46.6200, 125.1200)
    downstream = _case(db, "CHAIN-API-003", "加油站", base_time + timedelta(days=5), 46.6500, 125.1500)
    ChainAnalysisService.scan_chain_links(midstream.id, db)

    listed = client.get("/api/chain-links/", params={"case_id": midstream.id})
    assert listed.status_code == 200
    payload = listed.json()
    assert len(payload) == 2

    upstream_link = next(item for item in payload if item["case_id_a"] == upstream.id)
    confirmed = client.post(f"/api/chain-links/{upstream_link['id']}/confirm", json={"operator": "张三"})
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["confirmed_by"] == "张三"

    downstream_link = next(item for item in payload if item["case_id_b"] == downstream.id)
    rejected = client.post(f"/api/chain-links/{downstream_link['id']}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    map_data = client.get("/api/chain-links/map-data")
    assert map_data.status_code == 200
    visible = map_data.json()["chain_links"]
    assert len(visible) == 1
    assert visible[0]["status"] == "confirmed"
    assert visible[0]["from_case"]["id"] == upstream.id
    assert visible[0]["to_case"]["id"] == midstream.id
