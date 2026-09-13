import io
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import map_foundation
from app.database import Base, get_db
from app.models.map_foundation import (
    JurisdictionAssetVersion,
    MapFeatureClaim,
    MapImportTemplate,
    MapIngestRun,
    MapSource,
    OperationalArea,
)
from app.models.jurisdiction import JurisdictionAsset
from app.models.user import User


@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_local()
    session.add(
        User(
            id=1,
            username="map-admin",
            display_name="Map Admin",
            password_hash="test-only",
            role="admin",
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _client(db: Session, role: str = "admin") -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def principal(request: Request, call_next):
        request.state.principal = SimpleNamespace(
            user_id=1,
            role=role,
            username="tester",
        )
        return await call_next(request)

    app.include_router(map_foundation.router, prefix="/api")

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _create_source(client: TestClient) -> dict:
    response = client.post(
        "/api/map-sources",
        json={
            "source_key": "production-ledger",
            "name": "生产井台账",
            "source_type": "ledger",
            "trust_rank": 100,
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_template(client: TestClient, source_id: int) -> dict:
    response = client.post(
        "/api/map-import-templates",
        json={
            "source_id": source_id,
            "name": "井台账模板",
            "header_row": 1,
            "field_mapping": {
                "external_id": "井号",
                "name": "井名",
                "asset_type": "类型",
                "longitude": "经度",
                "latitude": "纬度",
            },
            "coordinate_system": "wgs84",
            "axis_order": "lon_lat",
            "coordinate_unit": "degree",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_map_source_creation_bootstraps_default_operational_area(db_session: Session):
    client = _client(db_session)

    source = _create_source(client)

    assert source["operational_area"]["code"] == "default-factory"
    assert source["status"] == "active"
    assert db_session.query(OperationalArea).count() == 1


def test_admin_can_create_and_update_versioned_operational_area_boundary(db_session: Session):
    client = _client(db_session)

    created = client.post(
        "/api/operational-areas",
        json={
            "code": "north-factory",
            "name": "北部厂区",
            "boundary": [124.0, 46.0, 126.0, 47.0],
            "is_default": True,
        },
    )
    updated = client.put(
        f"/api/operational-areas/{created.json()['id']}",
        json={"name": "北部生产区域"},
    )

    assert created.status_code == 201
    assert created.json()["is_default"] is True
    assert updated.status_code == 200
    assert updated.json()["name"] == "北部生产区域"


def test_invalid_operational_area_boundary_is_rejected(db_session: Session):
    response = _client(db_session).post(
        "/api/operational-areas",
        json={
            "code": "invalid-boundary",
            "name": "异常边界",
            "boundary": [126.0, 47.0, 124.0, 46.0],
        },
    )

    assert response.status_code == 422
    assert db_session.query(OperationalArea).count() == 0


def test_only_admin_can_manage_map_sources(db_session: Session):
    client = _client(db_session, role="analyst")

    response = client.post(
        "/api/map-sources",
        json={
            "source_key": "forbidden",
            "name": "越权数据源",
            "source_type": "ledger",
        },
    )

    assert response.status_code == 403
    assert db_session.query(MapSource).count() == 0


def test_preview_without_template_never_publishes_unknown_coordinates(db_session: Session):
    client = _client(db_session)
    source = _create_source(client)
    csv_content = "井号,井名,类型,经度,纬度\nW-001,南区1号井,well,125.101,46.601\n"

    response = client.post(
        f"/api/map-sources/{source['id']}/preview",
        files={"file": ("wells.csv", csv_content.encode("utf-8-sig"), "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["publishable"] is False
    assert payload["valid_rows"] == 0
    assert payload["quarantined_rows"] == 1
    assert payload["errors"][0]["code"] == "coordinate_system_required"
    assert db_session.query(JurisdictionAsset).count() == 0
    assert db_session.query(MapFeatureClaim).count() == 0


def test_ingest_publishes_valid_rows_with_provenance_and_quarantines_invalid_rows(
    db_session: Session,
):
    client = _client(db_session)
    source = _create_source(client)
    template = _create_template(client, source["id"])
    csv_content = (
        "井号,井名,类型,经度,纬度\n"
        "W-001,南区1号井,well,125.101,46.601\n"
        "W-002,坐标异常井,well,225.000,46.602\n"
    )

    response = client.post(
        f"/api/map-sources/{source['id']}/ingest",
        params={"template_id": template["id"], "source_revision": "2026-09-08"},
        files={"file": ("wells.csv", csv_content.encode("utf-8-sig"), "text/csv")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "completed_with_errors"
    assert payload["total_rows"] == 2
    assert payload["valid_rows"] == 1
    assert payload["quarantined_rows"] == 1
    assert payload["created_assets"] == 1

    asset = db_session.query(JurisdictionAsset).one()
    assert asset.external_id == "W-001"
    assert asset.canonical_key.startswith("area:1:")
    assert asset.coordinate_system == "epsg:4326"
    assert asset.verification_state == "source_verified"
    assert asset.operational_area_id == source["operational_area"]["id"]

    claims = db_session.query(MapFeatureClaim).order_by(MapFeatureClaim.row_number).all()
    assert [item.status for item in claims] == ["published", "quarantined"]
    assert claims[0].asset_id == asset.id
    assert claims[0].raw_hash
    assert claims[1].error_code == "coordinate_out_of_range"


def test_ingest_is_idempotent_for_same_source_revision_and_file(db_session: Session):
    client = _client(db_session)
    source = _create_source(client)
    template = _create_template(client, source["id"])
    csv_content = "井号,井名,类型,经度,纬度\nW-001,南区1号井,well,125.101,46.601\n"
    files = {"file": ("wells.csv", csv_content.encode("utf-8-sig"), "text/csv")}

    first = client.post(
        f"/api/map-sources/{source['id']}/ingest",
        params={"template_id": template["id"], "source_revision": "rev-1"},
        files=files,
    )
    second = client.post(
        f"/api/map-sources/{source['id']}/ingest",
        params={"template_id": template["id"], "source_revision": "rev-1"},
        files={"file": ("wells.csv", csv_content.encode("utf-8-sig"), "text/csv")},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["idempotent_replay"] is True
    assert db_session.query(MapIngestRun).count() == 1
    assert db_session.query(JurisdictionAsset).count() == 1
    assert db_session.query(MapFeatureClaim).count() == 1


def test_template_rejects_unknown_coordinate_system(db_session: Session):
    client = _client(db_session)
    source = _create_source(client)

    response = client.post(
        "/api/map-import-templates",
        json={
            "source_id": source["id"],
            "name": "未知坐标模板",
            "field_mapping": {"name": "井名", "longitude": "X", "latitude": "Y"},
            "coordinate_system": "unknown",
        },
    )

    assert response.status_code == 422
    assert db_session.query(MapImportTemplate).count() == 0


def test_ingest_never_changes_case_records(db_session: Session):
    from datetime import datetime

    from app.models.case import Case

    case = Case(
        case_number="MAP-GUARD-001",
        occurred_time=datetime(2026, 9, 8, 1, 0),
        location="原始案发地点",
        latitude=46.6,
        longitude=125.1,
    )
    db_session.add(case)
    db_session.commit()
    original = (case.location, case.latitude, case.longitude, case.features)

    client = _client(db_session)
    source = _create_source(client)
    template = _create_template(client, source["id"])
    csv_content = "井号,井名,类型,经度,纬度\nW-001,南区1号井,well,125.101,46.601\n"
    response = client.post(
        f"/api/map-sources/{source['id']}/ingest",
        params={"template_id": template["id"]},
        files={"file": ("wells.csv", io.BytesIO(csv_content.encode("utf-8-sig")), "text/csv")},
    )

    assert response.status_code == 201
    db_session.refresh(case)
    assert (case.location, case.latitude, case.longitude, case.features) == original


def test_public_map_reference_is_not_marked_as_verified_business_fact(db_session: Session):
    client = _client(db_session)
    source_response = client.post(
        "/api/map-sources",
        json={
            "source_key": "public-reference",
            "name": "公共地图参考",
            "source_type": "public_map",
            "trust_rank": 10,
        },
    )
    source = source_response.json()
    template = _create_template(client, source["id"])

    response = client.post(
        f"/api/map-sources/{source['id']}/ingest",
        params={"template_id": template["id"]},
        files={
            "file": (
                "roads.csv",
                "井号,井名,类型,经度,纬度\nR-1,外围道路,road,125.101,46.601\n".encode("utf-8-sig"),
                "text/csv",
            )
        },
    )

    assert response.status_code == 201
    asset = db_session.query(JurisdictionAsset).one()
    assert asset.verified is False
    assert asset.verification_state == "reference_only"
    assert db_session.query(JurisdictionAssetVersion).count() == 1


def test_higher_trust_source_updates_same_cross_source_asset(db_session: Session):
    client = _client(db_session)
    public = client.post(
        "/api/map-sources",
        json={
            "source_key": "public-wells",
            "name": "公共井点参考",
            "source_type": "public_map",
            "trust_rank": 10,
        },
    ).json()
    public_template = _create_template(client, public["id"])
    public_file = "井号,井名,类型,经度,纬度\nPUBLIC-1,南区1号井,well,125.100,46.600\n"
    assert client.post(
        f"/api/map-sources/{public['id']}/ingest",
        params={"template_id": public_template["id"]},
        files={"file": ("public.csv", public_file.encode("utf-8-sig"), "text/csv")},
    ).status_code == 201

    production = client.post(
        "/api/map-sources",
        json={
            "source_key": "production-wells",
            "name": "生产井台账",
            "source_type": "ledger",
            "trust_rank": 100,
        },
    ).json()
    production_template = _create_template(client, production["id"])
    production_file = "井号,井名,类型,经度,纬度\nINNER-9001,南区1号井,well,125.102,46.602\n"
    response = client.post(
        f"/api/map-sources/{production['id']}/ingest",
        params={"template_id": production_template["id"]},
        files={"file": ("production.csv", production_file.encode("utf-8-sig"), "text/csv")},
    )

    assert response.status_code == 201
    assert response.json()["updated_assets"] == 1
    assert db_session.query(JurisdictionAsset).count() == 1
    asset = db_session.query(JurisdictionAsset).one()
    assert asset.longitude == pytest.approx(125.102)
    assert asset.attributes["source_key"] == "production-wells"


def test_lower_trust_source_never_overwrites_verified_ledger_asset(db_session: Session):
    client = _client(db_session)
    production = client.post(
        "/api/map-sources",
        json={
            "source_key": "trusted-ledger",
            "name": "生产主台账",
            "source_type": "ledger",
        },
    ).json()
    production_template = _create_template(client, production["id"])
    assert client.post(
        f"/api/map-sources/{production['id']}/ingest",
        params={"template_id": production_template["id"]},
        files={
            "file": (
                "ledger.csv",
                "井号,井名,类型,经度,纬度\nINNER-1,同名井,well,125.100,46.600\n".encode("utf-8-sig"),
                "text/csv",
            )
        },
    ).status_code == 201
    public = client.post(
        "/api/map-sources",
        json={
            "source_key": "untrusted-public",
            "name": "公共参考",
            "source_type": "public_map",
        },
    ).json()
    public_template = _create_template(client, public["id"])

    response = client.post(
        f"/api/map-sources/{public['id']}/ingest",
        params={"template_id": public_template["id"]},
        files={
            "file": (
                "public.csv",
                "井号,井名,类型,经度,纬度\nPUBLIC-1,同名井,well,125.100,46.600\n".encode("utf-8-sig"),
                "text/csv",
            )
        },
    )

    assert response.status_code == 201
    assert response.json()["quarantined_rows"] == 1
    asset = db_session.query(JurisdictionAsset).one()
    assert asset.external_id == "INNER-1"
    assert asset.verified is True
    assert asset.source == "ledger"
    assert asset.attributes["source_key"] == "trusted-ledger"


def test_same_name_type_at_distant_coordinates_creates_distinct_assets(db_session: Session):
    client = _client(db_session)
    source = _create_source(client)
    template = _create_template(client, source["id"])
    content = (
        "井号,井名,类型,经度,纬度\n"
        "W-A,重复井名,well,125.100,46.600\n"
        "W-B,重复井名,well,126.100,47.600\n"
    )

    response = client.post(
        f"/api/map-sources/{source['id']}/ingest",
        params={"template_id": template["id"]},
        files={"file": ("distant.csv", content.encode("utf-8-sig"), "text/csv")},
    )

    assert response.status_code == 201
    assert response.json()["created_assets"] == 2
    assert db_session.query(JurisdictionAsset).count() == 2


def test_ingest_preserves_production_attributes_and_quarantines_outside_area(db_session: Session):
    client = _client(db_session)
    source = _create_source(client)
    area = db_session.query(OperationalArea).one()
    area.boundary = [125.0, 46.5, 125.2, 46.7]
    db_session.commit()
    template_response = client.post(
        "/api/map-import-templates",
        json={
            "source_id": source["id"],
            "name": "生产属性模板",
            "field_mapping": {
                "name": "井名",
                "asset_type": "类型",
                "longitude": "经度",
                "latitude": "纬度",
                "oil_type": "油品",
                "production_output": "日产量",
                "is_high_production": "是否高产",
                "water_cut_min": "含水率下限",
                "water_cut_max": "含水率上限",
                "water_cut_unit": "含水率单位",
                "production_valid_from": "有效开始",
                "production_valid_to": "有效结束",
            },
            "coordinate_system": "wgs84",
        },
    )
    template = template_response.json()
    content = (
        "井名,类型,经度,纬度,油品,日产量,是否高产,含水率下限,含水率上限,含水率单位,有效开始,有效结束\n"
        "范围内井,well,125.1,46.6,原油,95,是,20,40,percent,2026-09-01T00:00:00Z,2026-10-01T00:00:00Z\n"
        "范围外井,well,126.1,46.6,原油,80,否,,,,,\n"
    )

    response = client.post(
        f"/api/map-sources/{source['id']}/ingest",
        params={"template_id": template["id"]},
        files={"file": ("production.csv", content.encode("utf-8-sig"), "text/csv")},
    )

    assert response.status_code == 201
    assert response.json()["valid_rows"] == 1
    assert response.json()["quarantined_rows"] == 1
    asset = db_session.query(JurisdictionAsset).one()
    assert asset.attributes["oil_type"] == "原油"
    assert asset.attributes["production_output"] == 95.0
    assert asset.attributes["is_high_production"] is True
    assert asset.attributes["water_cut_min"] == 20.0
    assert asset.attributes["water_cut_max"] == 40.0
    assert asset.attributes["water_cut_unit"] == "percent"
    assert asset.attributes["production_valid_from"] == "2026-09-01T00:00:00+00:00"
    conflict = db_session.query(MapFeatureClaim).filter(
        MapFeatureClaim.status == "quarantined"
    ).one()
    assert conflict.error_code == "outside_operational_area"


@pytest.mark.parametrize("values,code", [
    (("60", "20", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"), "invalid_water_cut_range"),
    (("nan", "40", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"), "invalid_water_cut_range"),
    (("20", "40", "2026-09-01", "2026-10-01T00:00:00Z"), "invalid_production_time"),
    (("20", "40", "2026-10-01T00:00:00Z", "2026-09-01T00:00:00Z"), "invalid_production_time"),
])
def test_invalid_production_conditions_are_quarantined_without_publishing(db_session, values, code):
    client = _client(db_session)
    source = _create_source(client)
    fields = ("name", "asset_type", "longitude", "latitude", "water_cut_min", "water_cut_max",
              "production_valid_from", "production_valid_to")
    response = client.post("/api/map-import-templates", json={
        "source_id": source["id"], "name": "生产条件校验模板", "coordinate_system": "wgs84",
        "field_mapping": {field: field for field in fields},
    })
    assert response.status_code == 201
    content = ",".join(fields) + "\n" + ",".join(("待核验井", "well", "125.1", "46.6", *values)) + "\n"
    response = client.post(f"/api/map-sources/{source['id']}/ingest",
        params={"template_id": response.json()["id"]},
        files={"file": ("invalid.csv", content.encode("utf-8-sig"), "text/csv")})
    assert response.status_code == 201
    assert response.json()["valid_rows"] == 0 and response.json()["quarantined_rows"] == 1
    assert db_session.query(JurisdictionAsset).count() == 0
    assert db_session.query(MapFeatureClaim).one().error_code == code
