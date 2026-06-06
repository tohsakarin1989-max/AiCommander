import io
from datetime import datetime

import pytest
import openpyxl
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import jurisdiction
from app.database import Base, get_db
from app.models.case import Case
from app.models.patrol import PatrolRecord
from app.services.jurisdiction_service import JurisdictionService
from app.services.smart_analysis_service import SmartAnalysisService


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
    app.include_router(jurisdiction.router, prefix="/api/jurisdiction", tags=["jurisdiction"])

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _add_case(db_session: Session) -> Case:
    case = Case(
        case_number="JUR-20260427-001",
        occurred_time=datetime(2026, 4, 26, 2, 10, 0),
        location="南区 12 号井附近",
        latitude=39.9000,
        longitude=116.4000,
        case_type="盗油",
        oil_type="原油",
        facility_type="井口",
        modus_operandi="夜间车辆靠近盗油",
        source_type="巡逻发现",
        status="closed",
    )
    db_session.add(case)
    db_session.commit()
    db_session.refresh(case)
    return case


def _create_asset(
    client: TestClient,
    name: str,
    asset_type: str,
    latitude: float,
    longitude: float,
    **extra,
) -> dict:
    response = client.post(
        "/api/jurisdiction/assets",
        json={
            "name": name,
            "asset_type": asset_type,
            "geometry_type": "point",
            "latitude": latitude,
            "longitude": longitude,
            **extra,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_create_assets_and_summary(api_db_session: Session):
    client = _build_client(api_db_session)

    _create_asset(client, "南区12号井", "well", 39.9008, 116.4007, source="manual")
    _create_asset(client, "南区便道", "road", 39.9010, 116.4000, source="map")
    _create_asset(client, "东湾村", "village", 39.9100, 116.4070, source="map")

    assets = client.get("/api/jurisdiction/assets")
    summary = client.get("/api/jurisdiction/assets/summary")

    assert assets.status_code == 200
    assert len(assets.json()) == 3
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["total"] == 3
    assert payload["by_type"]["road"] == 1
    assert payload["by_source"]["map"] == 2
    assert payload["by_layer"]["public_map_reference"] == 2
    assert payload["by_layer"]["oil_business_asset"] == 1


def test_bulk_import_assets_marks_map_source(api_db_session: Session):
    client = _build_client(api_db_session)

    response = client.post(
        "/api/jurisdiction/assets/bulk",
        json={
            "items": [
                {
                    "name": "东侧主路",
                    "asset_type": "road",
                    "latitude": 39.902,
                    "longitude": 116.401,
                    "source": "map",
                },
                {
                    "name": "北湾村",
                    "asset_type": "village",
                    "latitude": 39.91,
                    "longitude": 116.407,
                    "source": "map",
                },
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["created"] == 2
    assert payload["total"] == 2
    assert payload["items"][0]["source"] == "map"


def test_geojson_import_creates_and_updates_assets(api_db_session: Session):
    client = _build_client(api_db_session)
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "id": "road-001",
                    "name": "南区东侧便道",
                    "asset_type": "road",
                    "risk_level": 2,
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[116.4000, 39.9000], [116.4040, 39.9040]],
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "id": "village-001",
                    "name": "东湾村",
                    "asset_type": "village",
                },
                "geometry": {"type": "Point", "coordinates": [116.4070, 39.9100]},
            },
        ],
    }

    created = client.post("/api/jurisdiction/assets/import-geojson", json={"geojson": geojson})
    updated = client.post(
        "/api/jurisdiction/assets/import-geojson",
        json={
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "id": "road-001",
                            "name": "南区东侧便道-已校验",
                            "asset_type": "road",
                            "risk_level": 3,
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[116.4000, 39.9000], [116.4040, 39.9040]],
                        },
                    }
                ],
            }
        },
    )

    assert created.status_code == 200
    assert created.json()["created"] == 2
    assert created.json()["updated"] == 0
    assert created.json()["items"][0]["source"] == "map"
    assert created.json()["items"][0]["latitude"] == pytest.approx(39.902)
    assert updated.status_code == 200
    assert updated.json()["created"] == 0
    assert updated.json()["updated"] == 1
    assets = client.get("/api/jurisdiction/assets", params={"status": ""}).json()
    assert len(assets) == 2
    assert any(asset["name"] == "南区东侧便道-已校验" for asset in assets)


def test_sync_public_map_references_fetches_osm_and_upserts(api_db_session: Session, monkeypatch):
    client = _build_client(api_db_session)
    _add_case(api_db_session)

    def fake_fetch(query: str):
        assert "way[\"highway\"]" in query
        assert "node[\"place\"" in query
        return [
            {
                "type": "way",
                "id": 1001,
                "tags": {"highway": "service", "name": "南区东侧道路"},
                "geometry": [
                    {"lat": 39.9000, "lon": 116.4000},
                    {"lat": 39.9040, "lon": 116.4040},
                ],
            },
            {
                "type": "node",
                "id": 2001,
                "lat": 39.9100,
                "lon": 116.4070,
                "tags": {"place": "village", "name": "东湾村"},
            },
            {
                "type": "way",
                "id": 3001,
                "tags": {"waterway": "stream", "name": "南侧排水沟"},
                "geometry": [
                    {"lat": 39.8990, "lon": 116.3980},
                    {"lat": 39.9020, "lon": 116.4020},
                ],
            },
        ]

    monkeypatch.setattr(JurisdictionService, "_fetch_public_map_elements", staticmethod(fake_fetch))

    created = client.post("/api/jurisdiction/assets/sync-public-map", json={"radius_km": 1, "max_features": 10})
    updated = client.post("/api/jurisdiction/assets/sync-public-map", json={"radius_km": 1, "max_features": 10})

    assert created.status_code == 200
    payload = created.json()
    assert payload["provider"] == "openstreetmap"
    assert payload["pulled"] == 3
    assert payload["usable"] == 3
    assert payload["created"] == 3
    assert payload["updated"] == 0
    assert payload["items"][0]["source"] == "map"
    assert payload["items"][0]["verified"] is True
    assert payload["items"][0]["external_id"] == "osm:way:1001"
    assert {item["asset_type"] for item in payload["items"]} == {"road", "village", "river"}
    assert updated.status_code == 200
    assert updated.json()["created"] == 0
    assert updated.json()["updated"] == 3


def test_update_and_deactivate_asset(api_db_session: Session):
    client = _build_client(api_db_session)
    asset = _create_asset(client, "待编辑井口", "well", 39.9000, 116.4000)

    updated = client.put(
        f"/api/jurisdiction/assets/{asset['id']}",
        json={
            "name": "已编辑井口",
            "latitude": 39.9012,
            "longitude": 116.4012,
            "risk_level": 4,
            "verified": True,
            "tags": ["重点", "夜巡"],
        },
    )
    deleted = client.delete(f"/api/jurisdiction/assets/{asset['id']}")
    active_assets = client.get("/api/jurisdiction/assets").json()
    inactive_assets = client.get("/api/jurisdiction/assets", params={"status": "inactive"}).json()

    assert updated.status_code == 200
    assert updated.json()["name"] == "已编辑井口"
    assert updated.json()["risk_level"] == 4
    assert updated.json()["verified"] is True
    assert updated.json()["tags"] == ["重点", "夜巡"]
    assert updated.json()["geometry"]["type"] == "Point"
    assert updated.json()["geometry"]["coordinates"] == [116.4012, 39.9012]
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "inactive"
    assert active_assets == []
    assert inactive_assets[0]["id"] == asset["id"]


def test_tabular_asset_import_supports_preview_and_xlsx_commit(api_db_session: Session):
    client = _build_client(api_db_session)
    csv_content = (
        "external_id,name,asset_type,latitude,longitude,source,risk_level,verified,tags\n"
        "well-001,南区12号井,well,39.9008,116.4007,ledger,3,是,井口;重点\n"
        "road-001,南区便道,road,39.9010,116.4000,ledger,2,否,\n"
    )

    preview = client.post(
        "/api/jurisdiction/assets/import-table",
        params={"dry_run": "true"},
        files={"file": ("assets.csv", csv_content.encode("utf-8-sig"), "text/csv")},
    )
    assert preview.status_code == 200
    assert preview.json()["valid"] == 2
    assert preview.json()["created"] == 0
    assert client.get("/api/jurisdiction/assets", params={"status": ""}).json() == []

    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.append(["external_id", "name", "asset_type", "latitude", "longitude", "source", "risk_level", "verified"])
    worksheet.append(["well-001", "南区12号井-台账更新", "well", 39.9009, 116.4008, "ledger", 4, "是"])
    worksheet.append(["village-001", "东湾村", "village", 39.91, 116.407, "ledger", 1, "是"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    committed = client.post(
        "/api/jurisdiction/assets/import-table",
        files={
            "file": (
                "assets.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert committed.status_code == 200
    payload = committed.json()
    assert payload["valid"] == 2
    assert payload["created"] == 2
    assert payload["updated"] == 0
    assert payload["items"][0]["name"] == "南区12号井-台账更新"

    duplicate_update = client.post(
        "/api/jurisdiction/assets/import-table",
        files={"file": ("assets.csv", csv_content.encode("utf-8-sig"), "text/csv")},
    )
    assert duplicate_update.status_code == 200
    assert duplicate_update.json()["created"] == 1
    assert duplicate_update.json()["updated"] == 1
    assets = client.get("/api/jurisdiction/assets", params={"status": ""}).json()
    assert len(assets) == 3
    assert any(asset["name"] == "南区12号井" for asset in assets)


def test_case_risk_context_uses_nearest_assets(api_db_session: Session):
    client = _build_client(api_db_session)
    case = _add_case(api_db_session)
    _create_asset(client, "南区便道", "road", 39.9010, 116.4000)
    _create_asset(client, "东湾村", "village", 39.9100, 116.4070)
    _create_asset(client, "南区监控点", "camera", 39.9200, 116.4300)
    _create_asset(client, "南区12号井", "well", 39.9008, 116.4007)

    response = client.get(f"/api/jurisdiction/cases/{case.id}/risk-context")

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == case.id
    assert payload["has_geo"] is True
    assert payload["nearest"]["road"]["asset"]["name"] == "南区便道"
    assert payload["nearest"]["production_target"]["asset"]["name"] == "南区12号井"
    assert payload["risk_score"] > 0
    assert any("道路" in condition for condition in payload["risk_conditions"])
    assert any("技防" in action or "监控" in action for action in payload["prevention_opportunities"])


def test_similar_targets_explain_matching_conditions(api_db_session: Session):
    client = _build_client(api_db_session)
    case = _add_case(api_db_session)
    _create_asset(client, "已发案便道", "road", 39.9010, 116.4000)
    _create_asset(client, "已发案村屯", "village", 39.9100, 116.4070)
    _create_asset(client, "已发案井口", "well", 39.9008, 116.4007)
    similar = _create_asset(client, "相似条件井口", "well", 39.8990, 116.3995)
    _create_asset(client, "低相似井口", "well", 40.2000, 116.9000)

    response = client.get(
        "/api/jurisdiction/similar-targets",
        params={"case_id": case.id, "limit": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == case.id
    assert payload["items"][0]["asset"]["id"] == similar["id"]
    assert payload["items"][0]["similarity_score"] >= 60
    assert payload["items"][0]["reasons"]


def test_case_experience_card_extracts_reusable_lessons(api_db_session: Session):
    client = _build_client(api_db_session)
    case = _add_case(api_db_session)
    _create_asset(client, "南区便道", "road", 39.9010, 116.4000)
    _create_asset(client, "东湾村", "village", 39.9100, 116.4070)
    _create_asset(client, "南区12号井", "well", 39.9008, 116.4007)

    response = client.get(f"/api/jurisdiction/cases/{case.id}/experience-card")

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == case.id
    assert payload["time_pattern"]["period"] == "凌晨"
    assert "夜间车辆靠近盗油" in payload["modus_tags"]
    assert payload["spatial_conditions"]
    assert payload["reusable_lessons"]


def test_asset_risk_profile_links_cases_and_environment(api_db_session: Session):
    client = _build_client(api_db_session)
    case = _add_case(api_db_session)
    _create_asset(client, "南区便道", "road", 39.9010, 116.4000)
    asset = _create_asset(client, "南区12号井", "well", 39.9008, 116.4007)

    response = client.get(f"/api/jurisdiction/assets/{asset['id']}/risk-profile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset"]["id"] == asset["id"]
    assert payload["risk_score"] >= 30
    assert payload["related_cases"][0]["id"] == case.id
    assert payload["risk_reasons"]


def test_data_quality_audit_detects_gaps_and_duplicates(api_db_session: Session):
    client = _build_client(api_db_session)
    _create_asset(client, "重复井口", "well", 39.9000, 116.4000)
    _create_asset(client, "重复井口", "well", 39.9001, 116.4001)
    client.post(
        "/api/jurisdiction/assets",
        json={"name": "缺坐标监控", "asset_type": "camera", "source": "manual"},
    )

    response = client.get("/api/jurisdiction/data-quality")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_assets"] == 3
    assert payload["missing_coordinates"] == 1
    assert payload["duplicate_candidates"] >= 1
    assert payload["coverage_score"] < 100
    assert payload["recommendations"]
    assert "road" not in payload["missing_required_types"]
    assert "village" not in payload["missing_required_types"]
    assert set(payload["missing_public_reference_types"]) == {"road", "village"}
    assert any("公共地图参考数据" in item for item in payload["recommendations"])


def test_patrol_plan_roundtable_and_feedback_close_loop(api_db_session: Session):
    client = _build_client(api_db_session)
    case = _add_case(api_db_session)
    _create_asset(client, "南区便道", "road", 39.9010, 116.4000)
    _create_asset(client, "东湾村", "village", 39.9100, 116.4070)
    _create_asset(client, "南区12号井", "well", 39.9008, 116.4007)
    _create_asset(client, "东入口巡逻点", "patrol_point", 39.8995, 116.3985)

    plan = client.post("/api/jurisdiction/patrol-plan", json={"case_id": case.id})
    briefing = client.get("/api/jurisdiction/roundtable-briefing", params={"case_id": case.id})
    feedback = client.post(
        "/api/jurisdiction/feedback",
        json={
            "case_id": case.id,
            "feedback_type": "patrol",
            "adopted": True,
            "result": "夜间巡逻发现可疑车辆并劝离",
            "effectiveness_score": 82,
            "notes": "建议继续保留随机回访",
        },
    )
    effectiveness = client.get("/api/jurisdiction/effectiveness")

    assert plan.status_code == 200
    assert plan.json()["control_points"]
    assert plan.json()["time_windows"]
    assert briefing.status_code == 200
    assert "议题" in briefing.json()["agenda"][0]
    assert briefing.json()["tasks"]
    assert feedback.status_code == 200
    assert feedback.json()["effectiveness_score"] == 82
    assert effectiveness.status_code == 200
    assert effectiveness.json()["total_feedback"] == 1
    assert effectiveness.json()["adopted_count"] == 1


def test_prevention_workbench_aggregates_full_decision_context(api_db_session: Session):
    client = _build_client(api_db_session)
    case = _add_case(api_db_session)
    _create_asset(client, "南区便道", "road", 39.9010, 116.4000)
    _create_asset(client, "东湾村", "village", 39.9100, 116.4070)
    _create_asset(client, "南区12号井", "well", 39.9008, 116.4007)
    _create_asset(client, "相似条件井口", "well", 39.8990, 116.3995)

    response = client.get("/api/jurisdiction/prevention-workbench", params={"case_id": case.id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == case.id
    assert payload["experience_card"]["case_id"] == case.id
    assert payload["similar_targets"]["items"]
    assert payload["patrol_plan"]["control_points"]
    assert payload["roundtable_briefing"]["tasks"]
    assert "data_quality" in payload


def test_materialize_patrol_plan_creates_patrol_records(api_db_session: Session):
    client = _build_client(api_db_session)
    case = _add_case(api_db_session)
    _create_asset(client, "南区便道", "road", 39.9010, 116.4000)
    _create_asset(client, "东湾村", "village", 39.9100, 116.4070)
    _create_asset(client, "南区12号井", "well", 39.9008, 116.4007)
    _create_asset(client, "相似条件井口", "well", 39.8990, 116.3995)

    response = client.post(
        "/api/jurisdiction/patrol-plan/materialize",
        json={
            "case_id": case.id,
            "limit": 3,
            "officer_count": 2,
            "created_by": "jurisdiction-workbench",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["created_count"] >= 1
    assert payload["patrol_records"][0]["status"] == "planned"
    assert payload["patrol_records"][0]["patrol_type"] == "targeted"
    patrols = api_db_session.query(PatrolRecord).all()
    assert len(patrols) == payload["created_count"]
    assert patrols[0].related_case_ids == [case.id]
    assert patrols[0].area_coordinates[0]["asset_id"] is not None

    duplicate = client.post(
        "/api/jurisdiction/patrol-plan/materialize",
        json={
            "case_id": case.id,
            "limit": 3,
            "created_by": "jurisdiction-workbench",
        },
    )

    assert duplicate.status_code == 200
    assert duplicate.json()["created_count"] == 0
    assert duplicate.json()["skipped_count"] == payload["created_count"]
    assert api_db_session.query(PatrolRecord).count() == payload["created_count"]


@pytest.mark.asyncio
async def test_smart_analysis_includes_jurisdiction_module(api_db_session: Session):
    client = _build_client(api_db_session)
    _add_case(api_db_session)
    _create_asset(client, "南区便道", "road", 39.9010, 116.4000, verified=True)
    _create_asset(client, "东湾村", "village", 39.9100, 116.4070, verified=True)
    _create_asset(client, "南区12号井", "well", 39.9008, 116.4007, verified=True)

    report = await SmartAnalysisService(api_db_session).analyze(
        time_window_days=30,
        min_cases=1,
        include_deployment=True,
    )

    assert "jurisdiction" in report["modules"]
    jurisdiction_module = report["modules"]["jurisdiction"]
    assert jurisdiction_module["data_quality"]["coverage_score"] >= 80
    assert jurisdiction_module["patrol_plan"]["control_points"]
    assert any(
        item["category"] == "jurisdiction"
        for item in report["priority_actions"]
    )
