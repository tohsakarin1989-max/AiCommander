"""道路预检契约：保留线形、失败关闭、无写入与当前辖区权限。"""
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.map_foundation import router
from app.database import get_db
from app.models.map_foundation import MapSource, OperationalArea
from app.services.internal_road_import import preview_internal_roads
from test_map_foundation import db_session, _client  # noqa: F401


def feature(identifier="road-1"):
    return {"type": "Feature", "id": identifier,
            "geometry": {"type": "MultiLineString", "coordinates": [
                [[125, 46], [125.01, 46.01], [125.02, 46.02]],
                [[125.03, 46.03], [125.04, 46.04]]]},
            "properties": {"kind": "road", "name": "生产路", "conditions": {}}}


def collection(*features):
    return {"type": "FeatureCollection", "coordinate_system": "EPSG:4326",
            "features": list(features or [feature()])}


def test_same_named_segments_preserve_all_nodes_without_inferred_permissions():
    payload = collection(feature(), feature("road-2"))
    original = deepcopy(payload)
    result = preview_internal_roads(payload)
    assert result["valid"] == 2
    assert result["vertices"] == 10
    assert [r["feature"] for r in result["rows"]] == original["features"]
    assert all(r["status"] == "pending_verification" for r in result["rows"])
    assert not result["routing_available"] and not result["persisted"]
    result["rows"][0]["feature"]["properties"]["name"] = "修改返回值"
    assert payload == original
    assert preview_internal_roads(payload)["input_sha256"] == result["input_sha256"]


def test_duplicate_identifiers_are_all_rejected():
    result = preview_internal_roads(collection(feature(), feature()))
    assert result["valid"] == 0
    assert all("本批来源编号重复" in r["errors"][0] for r in result["rows"])


@pytest.mark.parametrize("point", [[None, 46], [True, 46], ["125", 46], [181, 46], [125, 91], [125, 46, 3]])
def test_coordinates_are_not_coerced(point):
    road = feature()
    road["geometry"] = {"type": "LineString", "coordinates": [point, [125, 46]]}
    assert preview_internal_roads(collection(road))["valid"] == 0


@pytest.mark.parametrize("conditions", [
    {"access": True}, {"max_height_m": True}, {"max_weight_t": -1},
    {"ignore_restrictions": True}, {"valid_from": "2026-09-11"},
    {"valid_from": "2026-09-12T00:00:00+08:00", "valid_until": "2026-09-11T00:00:00+08:00"},
])
def test_invalid_conditions_remain_invalid(conditions):
    road = feature()
    road["properties"]["conditions"] = conditions
    assert preview_internal_roads(collection(road))["valid"] == 0


def test_malformed_geometry_type_is_a_row_error_not_batch_crash():
    road = feature()
    road["geometry"]["type"] = []
    assert preview_internal_roads(collection(road))["rows"][0]["status"] == "invalid"


def test_missing_entrance_link_does_not_snap_to_another_road():
    entrance = {"type": "Feature", "id": "gate-1",
                "geometry": {"type": "Point", "coordinates": [125, 46]},
                "properties": {"kind": "entrance", "name": "入口", "road_id": "absent-road"}}
    row = preview_internal_roads(collection(feature(), entrance))["rows"][1]
    assert row["status"] == "pending_verification"
    assert len(row["warnings"]) == 2
    assert row["feature"] == entrance


@pytest.fixture
def source(db_session):
    db_session.add(OperationalArea(id=1, code="roads", name="测试厂区"))
    db_session.flush()
    db_session.add(MapSource(id=1, source_key="roads", name="内部道路",
                             source_type="internal_gis", operational_area_id=1))
    db_session.commit()
    db_session.info["authorized_area_ids"] = (1,)
    return 1


def test_api_read_only_and_current_scope(db_session, source):
    client = _client(db_session)
    url = f"/api/map-sources/{source}/roads/preview"
    result = client.post(url, json=collection())
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert not result.json()["persisted"]
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    db_session.info["authorized_area_ids"] = ()
    assert client.post(url, json=collection()).status_code == 404
    db_session.info.pop("authorized_area_ids")
    assert client.post(url, json=collection()).status_code == 403


def test_api_rejects_public_source_role_and_malformed_payload(db_session, source):
    url = f"/api/map-sources/{source}/roads/preview"
    assert _client(db_session, "analyst").post(url, json=collection()).status_code == 403
    client = _client(db_session)
    assert client.post(url, content=b"not-json").status_code == 422
    assert client.post(url, content=b"x" * (2 * 1024 * 1024 + 1)).status_code == 413
    row = db_session.query(MapSource).filter_by(id=source).one()
    row.source_type = "public_map"
    db_session.commit()
    assert client.post(url, json=collection()).status_code == 409


def test_api_requires_login_even_when_development_auth_disabled(db_session, source):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db_session
    assert TestClient(app).post(f"/api/map-sources/{source}/roads/preview", json=collection()).status_code == 401


def test_ingest_is_idempotent_and_preserves_source_history(db_session, source):
    from app.models.internal_roads import InternalRoadImport

    db_session.info["area_access_levels"] = {1: "manage"}
    client = _client(db_session)
    url = f"/api/map-sources/{source}/roads/ingest"
    payload = collection(feature(), feature("road-2"))
    first = client.post(url, json=payload)
    assert first.status_code == 201
    repeat = client.post(url, json=payload)
    assert repeat.status_code == 200
    assert repeat.json()["id"] == first.json()["id"]
    payload["features"][0]["properties"]["conditions"] = {"gate": "closed"}
    changed = client.post(url, json=payload)
    assert changed.status_code == 201
    assert changed.json()["id"] != first.json()["id"]
    old_url = f"/api/map-sources/{source}/roads/imports/{first.json()['id']}"
    old = client.get(old_url)
    assert old.json()["features"][0]["properties"]["conditions"] == {}
    assert old.json()["status"] == "pending_verification"
    assert not old.json()["routing_available"]
    assert db_session.query(InternalRoadImport).count() == 2
    db_session.info["authorized_area_ids"] = ()
    assert client.get(old_url).status_code == 404
    assert db_session.query(InternalRoadImport).count() == 0


def test_ingest_rejects_read_scope_and_invalid_batch_without_partial_save(db_session, source):
    from app.models.internal_roads import InternalRoadImport

    client = _client(db_session)
    url = f"/api/map-sources/{source}/roads/ingest"
    assert client.post(url, json=collection()).status_code == 403
    db_session.info["area_access_levels"] = {1: "read"}
    assert client.post(url, json=collection()).status_code == 403
    db_session.info["area_access_levels"] = {1: "write"}
    bad = feature("bad")
    bad["geometry"]["coordinates"] = []
    assert client.post(url, json=collection(feature(), bad)).status_code == 422
    assert db_session.query(InternalRoadImport).count() == 0


def test_incremental_road_migration_and_rollback(tmp_path, monkeypatch):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from app.config import settings

    backend = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{tmp_path / 'road-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(config, "09ac731646a1")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO operational_areas (id, code, name, is_default, status) "
                                "VALUES (991, 'migration-marker', '保留原数据', 0, 'active')"))
    command.upgrade(config, "3df0a64979d4")
    assert "internal_road_imports" in inspect(engine).get_table_names()
    assert "internal_road_feature_versions" in inspect(engine).get_table_names()
    assert "internal_road_reviews" in inspect(engine).get_table_names()
    assert {c["name"] for c in inspect(engine).get_columns("internal_road_imports")} >= {
        "source_id", "operational_area_id", "input_sha256", "features", "created_by"}
    command.downgrade(config, "09ac731646a1")
    assert "internal_road_imports" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name FROM operational_areas WHERE id=991")).scalar() == "保留原数据"
    command.upgrade(config, "3df0a64979d4")
    engine.dispose()


def test_review_binds_exact_version_and_does_not_grant_passage(db_session, source):
    from app.models.internal_roads import InternalRoadImport, InternalRoadReview

    db_session.info["area_access_levels"] = {1: "manage"}
    client = _client(db_session)
    base = f"/api/map-sources/{source}/roads"
    original = collection()
    imported = client.post(f"{base}/ingest", json=original).json()
    url = f"{base}/imports/{imported['id']}/features/road-1/reviews"
    data = {"input_sha256": imported["input_sha256"], "request_key": "review-0001",
            "previous_review_id": None, "decision": "verified", "note": "核对台账线形",
            "evidence_reference": "内部台账第1页"}
    first = client.post(url, json=data)
    assert first.status_code == 201
    assert not first.json()["routing_available"]
    repeated = client.post(url, json=data)
    assert repeated.status_code == 200 and repeated.json()["id"] == first.json()["id"]
    assert client.post(url, json={**data, "decision": "rejected"}).status_code == 409
    assert client.post(url, json={**data, "request_key": "review-0002"}).status_code == 409
    assert client.post(url, json={**data, "input_sha256": "0" * 64}).status_code == 409
    second = client.post(url, json={**data, "request_key": "review-0002", "decision": "pending_verification",
                                    "previous_review_id": first.json()["id"]})
    assert second.status_code == 201
    catalog = client.get(f"{base}/catalog").json()["items"][0]
    assert catalog["last_verified_import_id"] is None
    assert catalog["latest_review"]["decision"] == "pending_verification"
    assert db_session.query(InternalRoadReview).count() == 2
    history = client.get(url, params={"limit": 1}).json()
    assert history["items"][0]["id"] == second.json()["id"]
    older = client.get(url, params={"limit": 1, "before_id": history["next_before_id"]}).json()
    assert older["items"][0]["id"] == first.json()["id"]
    assert older["next_before_id"] is None
    latest = client.get(f"{base}/imports/{imported['id']}").json()
    assert latest["feature_reviews"]["road-1"]["id"] == second.json()["id"]
    assert db_session.query(InternalRoadImport).first().features == original["features"]
    original["features"][0]["properties"]["conditions"] = {"gate": "closed"}
    changed = client.post(f"{base}/ingest", json=original).json()
    listing = client.get(f"{base}/imports", params={"limit": 1}).json()
    assert listing["items"][0]["id"] == changed["id"]
    assert "features" not in listing["items"][0]
    assert client.get(f"{base}/imports", params={"before_id": listing["next_before_id"]}).json()["items"][0]["id"] == imported["id"]
    assert client.get(f"{base}/imports/{changed['id']}").json()["feature_reviews"]["road-1"] is None
    db_session.info["area_access_levels"] = {1: "read"}
    assert client.post(url, json=data).status_code == 403
    db_session.info["authorized_area_ids"] = ()
    assert client.get(f"{base}/imports/{imported['id']}").status_code == 404
    assert client.get(url).status_code == 404
    assert client.get(f"{base}/imports").status_code == 404
    assert db_session.query(InternalRoadReview).count() == 0


def test_catalog_migration_backfills_multiple_pages_without_changing_sources(tmp_path, monkeypatch):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, select, func
    from sqlalchemy.orm import Session
    from app.config import settings
    from app.models.user import User
    from app.models.internal_roads import InternalRoadImport, InternalRoadFeatureVersion

    backend = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{tmp_path / 'existing-road-data.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(config, "2cef953868c3")
    engine = create_engine(url)
    with Session(engine) as db:
        db.add(User(id=1, username="migration-admin", display_name="迁移测试", password_hash="test-only", role="admin"))
        db.add(OperationalArea(id=991, code="migration", name="合成区域"))
        db.flush()
        db.add(MapSource(id=1, source_key="roads", name="合成来源", source_type="internal_gis", operational_area_id=991))
        db.flush()
        for index in range(53):
            db.add(InternalRoadImport(source_id=1, operational_area_id=991, input_sha256=f"{index:064x}",
                schema_version="internal-road-preview-4.1.0-1", created_by=1, warnings=[],
                features=[feature("重复道路"), feature(f"road-{index}")]))
        db.commit()
        original = db.execute(select(InternalRoadImport.id, InternalRoadImport.features).order_by(InternalRoadImport.id)).all()
    for _ in range(2):
        command.upgrade(config, "3df0a64979d4")
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(InternalRoadFeatureVersion)) == 106
            assert db.execute(select(InternalRoadImport.id, InternalRoadImport.features).order_by(InternalRoadImport.id)).all() == original
            repeated = db.scalars(select(InternalRoadFeatureVersion).where(InternalRoadFeatureVersion.feature_id == "重复道路")).all()
            assert len(repeated) == 53
            assert all(row.source_id == 1 and row.operational_area_id == 991 for row in repeated)
        command.downgrade(config, "2cef953868c3")
    engine.dispose()


def test_entrance_checks_pin_declared_road_and_do_not_use_future_or_nearest(db_session, source):
    db_session.info["area_access_levels"] = {1: "manage"}
    client = _client(db_session)
    base = f"/api/map-sources/{source}/roads"
    first = client.post(f"{base}/ingest", json=collection(feature())).json()
    def entry(identifier, road_id, point):
        return {"type": "Feature", "id": identifier, "geometry": {"type": "Point", "coordinates": point},
                "properties": {"kind": "entrance", "name": "同名入口", "road_id": road_id}}
    payload = collection(entry("endpoint", "road-1", [125, 46]),
                         entry("vertex", "road-1", [125.01, 46.01]),
                         entry("no-match", "road-1", [125.0001, 46.0001]),
                         entry("missing", "future-road", [125, 46]),
                         entry("not-road", "endpoint", [125, 46]))
    imported = client.post(f"{base}/ingest", json=payload).json()
    url = f"{base}/imports/{imported['id']}"
    checks = {item["entrance_id"]: item for item in client.get(url).json()["entrance_checks"]}
    assert checks["endpoint"]["status"] == "coincident_endpoint_pending_verification"
    assert checks["vertex"]["status"] == "coincident_vertex_pending_verification"
    assert checks["no-match"]["status"] == "connection_geometry_pending_verification"
    assert checks["missing"]["status"] == "declared_road_missing"
    assert checks["not-road"]["status"] == "declared_target_not_road"
    assert checks["endpoint"]["road_import_id"] == first["id"]
    assert checks["endpoint"]["road_source_sha256"] == first["input_sha256"]
    assert all(item["connected"] is None and not item["routing_available"] for item in checks.values())
    assert client.post(f"{base}/ingest", json=collection(feature("future-road"))).status_code == 201
    later = {item["entrance_id"]: item for item in client.get(url).json()["entrance_checks"]}
    assert later == checks  # 新增未来道路不能倒灌历史入口检查。
    assert client.get(url).json()["features"] == payload["features"]


def test_compare_uses_identifiers_not_names_and_preserves_verified_history(db_session, source):
    db_session.info["area_access_levels"] = {1: "manage"}
    client = _client(db_session)
    base = f"/api/map-sources/{source}/roads"
    original = collection(feature(), feature("unchanged"), feature("omitted"))
    before = client.post(f"{base}/ingest", json=original).json()
    review = {"input_sha256": before["input_sha256"], "request_key": "compare-0001",
              "decision": "verified", "note": "来源核对", "evidence_reference": "台账第3页"}
    assert client.post(f"{base}/imports/{before['id']}/features/road-1/reviews", json=review).status_code == 201
    changed = deepcopy(original["features"][0])
    changed["geometry"]["coordinates"][0][1] = [125.015, 46.015]
    changed["properties"]["conditions"] = {"gate": "closed"}
    after = client.post(f"{base}/ingest", json=collection(changed, feature("unchanged"), feature("new"))).json()
    response = client.get(f"{base}/compare", params={"before_id": before["id"], "after_id": after["id"]})
    assert response.status_code == 200
    result = response.json()
    assert result["summary"] == {"changed": 1, "unchanged": 1, "not_provided": 1, "added": 1}
    rows = {item["source_feature_id"]: item for item in result["items"]}
    assert rows["road-1"]["changed_fields"] == ["geometry", "properties.conditions"]
    assert rows["road-1"]["affects_verified_source"]
    assert rows["road-1"]["after_review"] is None
    assert rows["road-1"]["before"] == original["features"][0]
    catalog = client.get(f"{base}/catalog").json()
    by_id = {item["source_feature_id"]: item for item in catalog["items"]}
    assert by_id["road-1"]["last_verified_import_id"] == before["id"]
    assert by_id["road-1"]["latest_import_id"] == after["id"]
    assert by_id["road-1"]["pending_update"]
    assert by_id["omitted"]["latest_import_id"] == before["id"]
    assert len(by_id) == 4  # 同名但不同编号不合并，缺失要素不自动删除。
    first_page = client.get(f"{base}/catalog", params={"limit": 1}).json()
    second_page = client.get(f"{base}/catalog", params={"after_feature": first_page["next_after_feature"]}).json()
    assert len(second_page["items"]) == 3
    assert rows["omitted"]["after"] is None
    assert not result["mutations_applied"] and not result["routing_available"]
    assert client.get(f"{base}/imports/{before['id']}").json()["features"] == original["features"]
    same = client.get(f"{base}/compare", params={"before_id": before["id"], "after_id": before["id"]}).json()
    assert same["summary"]["unchanged"] == 3
    assert not any(item["affects_verified_source"] for item in same["items"])
    assert client.get(f"{base}/compare", params={"before_id": before["id"], "after_id": 99999}).status_code == 404
    db_session.info["authorized_area_ids"] = ()
    assert client.get(f"{base}/compare", params={"before_id": before["id"], "after_id": after["id"]}).status_code == 404
    assert client.get(f"{base}/catalog").status_code == 404
