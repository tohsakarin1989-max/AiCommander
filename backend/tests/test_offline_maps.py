import base64
import hashlib
import io
import json
import sqlite3
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import offline_maps
from app.config import settings
from app.database import Base, get_db
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import (
    MapSnapshot,
    MapSnapshotFeature,
    OperationalArea,
    PublicMapBundle,
)
from app.services.map_foundation_service import MapFoundationService
from app.services.offline_map_service import OfflineMapService


VALID_PNG_TILE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session: Session, tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(settings, "MAP_PACKAGE_ROOT", str(tmp_path / "map-packages"))
    app = FastAPI()

    @app.middleware("http")
    async def principal(request: Request, call_next):
        request.state.principal = SimpleNamespace(user_id=None, role="admin")
        return await call_next(request)

    app.include_router(offline_maps.router, prefix="/api")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _mbtiles_bytes(
    tmp_path,
    tile: bytes | None = VALID_PNG_TILE,
    *,
    include_tile: bool = True,
    bounds: list[float] | None = None,
    tile_coordinate: tuple[int, int, int] = (0, 0, 0),
) -> bytes:
    path = tmp_path / f"source-{uuid4()}.mbtiles"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    connection.execute(
        "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
    )
    connection.execute("CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row)")
    connection.execute("INSERT INTO metadata VALUES ('format', 'png')")
    resolved_bounds = bounds or [124.0, 46.0, 126.0, 47.0]
    connection.execute(
        "INSERT INTO metadata VALUES ('bounds', ?)",
        (",".join(str(value) for value in resolved_bounds),),
    )
    connection.execute(
        "INSERT INTO metadata VALUES ('minzoom', ?)",
        (str(tile_coordinate[0]),),
    )
    connection.execute(
        "INSERT INTO metadata VALUES ('maxzoom', ?)",
        (str(tile_coordinate[0]),),
    )
    if include_tile:
        connection.execute("INSERT INTO tiles VALUES (?, ?, ?, ?)", (*tile_coordinate, tile))
    connection.commit()
    connection.close()
    return path.read_bytes()


def _bundle_bytes(
    tmp_path,
    *,
    valid_hash: bool = True,
    bundle_id: str = "public-2026-09-08",
    tile: bytes | None = VALID_PNG_TILE,
    include_tile: bool = True,
    attribution: str = "测试公共地图来源",
    bounds: list[float] | None = None,
    tile_coordinate: tuple[int, int, int] = (0, 0, 0),
) -> bytes:
    resolved_bounds = bounds or [124.0, 46.0, 126.0, 47.0]
    tiles = _mbtiles_bytes(
        tmp_path,
        tile,
        include_tile=include_tile,
        bounds=resolved_bounds,
        tile_coordinate=tile_coordinate,
    )
    digest = hashlib.sha256(tiles).hexdigest()
    manifest = {
        "schema_version": "1.0",
        "bundle_id": bundle_id,
        "provider": "openstreetmap",
        "source_version": "2026-09-08",
        "license": "ODbL-1.0",
        "attribution": attribution,
        "bounds": resolved_bounds,
        "min_zoom": tile_coordinate[0],
        "max_zoom": tile_coordinate[0],
        "tile_count": 1 if include_tile else 0,
        "contains_internal_data": False,
        "files": [
            {
                "name": "basemap.mbtiles",
                "sha256": digest if valid_hash else "0" * 64,
                "size": len(tiles),
            }
        ],
    }
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("basemap.mbtiles", tiles)
    return target.getvalue()


def _import_bundle(client: TestClient, tmp_path, bundle_id: str = "public-2026-09-08") -> dict:
    response = client.post(
        "/api/map-bundles/import",
        files={"file": ("public-map.zip", _bundle_bytes(tmp_path, bundle_id=bundle_id), "application/zip")},
    )
    assert response.status_code == 201
    return response.json()


def _default_area(db_session: Session):
    area = MapFoundationService.ensure_default_area(db_session)
    area.boundary = {
        "type": "Polygon",
        "coordinates": [[
            [124.5, 46.2],
            [125.5, 46.2],
            [125.5, 46.8],
            [124.5, 46.8],
            [124.5, 46.2],
        ]],
    }
    db_session.commit()
    return area


def test_import_build_publish_and_serve_tiles_offline(client: TestClient, db_session: Session, tmp_path):
    area = _default_area(db_session)
    bundle = _import_bundle(client, tmp_path)

    built = client.post(
        "/api/map-snapshots/build",
        json={"operational_area_id": area.id, "public_bundle_id": bundle["id"]},
    )
    assert built.status_code == 201
    assert built.json()["status"] == "ready"
    assert "http" not in json.dumps(built.json()["manifest"])

    published = client.post(f"/api/map-snapshots/{built.json()['id']}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "current"

    manifest = client.get("/api/maps/current/manifest")
    assert manifest.status_code == 200
    assert manifest.json()["tile_url"] == (
        f"/api/maps/tiles/{built.json()['id']}/{{z}}/{{x}}/{{y}}"
    )
    assert manifest.json()["min_zoom"] == 0
    assert manifest.json()["max_zoom"] == 0
    assert manifest.json()["attribution"] == "测试公共地图来源"

    tile = client.get("/api/maps/tiles/current/0/0/0")
    assert tile.status_code == 200
    assert tile.headers["content-type"] == "image/png"
    assert tile.headers["cache-control"] == "private, no-cache"
    assert tile.headers["vary"] == "Cookie, Authorization"
    assert tile.content.startswith(b"\x89PNG")

    pinned_tile = client.get(f"/api/maps/tiles/{built.json()['id']}/0/0/0")
    assert pinned_tile.status_code == 200
    assert pinned_tile.headers["cache-control"] == (
        "private, max-age=31536000, immutable"
    )

    assert db_session.query(PublicMapBundle).count() == 1
    assert db_session.query(MapSnapshot).filter(MapSnapshot.status == "current").count() == 1


def test_frontend_can_request_transparent_tile_outside_sparse_bundle(
    client: TestClient,
    db_session: Session,
    tmp_path,
):
    area = _default_area(db_session)
    bundle = _import_bundle(client, tmp_path, bundle_id="public-sparse")
    snapshot = client.post(
        "/api/map-snapshots/build",
        json={"operational_area_id": area.id, "public_bundle_id": bundle["id"]},
    ).json()
    assert client.post(f"/api/map-snapshots/{snapshot['id']}/publish").status_code == 200

    missing = client.get("/api/maps/tiles/current/1/0/0")
    placeholder = client.get("/api/maps/tiles/current/1/0/0?blank_missing=true")

    assert missing.status_code == 404
    assert placeholder.status_code == 200
    assert placeholder.headers["content-type"] == "image/gif"
    assert placeholder.headers["x-map-coverage"] == "outside"
    assert placeholder.content.startswith(b"GIF89a")


def test_bundle_checksum_mismatch_is_rejected_without_persisting(client: TestClient, db_session: Session, tmp_path):
    response = client.post(
        "/api/map-bundles/import",
        files={"file": ("tampered.zip", _bundle_bytes(tmp_path, valid_hash=False), "application/zip")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "地图包文件校验失败"
    assert db_session.query(PublicMapBundle).count() == 0


def test_import_rejects_non_object_manifest_file_entry_as_422(
    client: TestClient,
    db_session: Session,
    tmp_path,
):
    content = _bundle_bytes(tmp_path, bundle_id="invalid-file-entry")
    with zipfile.ZipFile(io.BytesIO(content), "r") as source:
        manifest = json.loads(source.read("manifest.json"))
        mbtiles = source.read("basemap.mbtiles")
    manifest["files"] = [1]
    malformed = io.BytesIO()
    with zipfile.ZipFile(malformed, "w", compression=zipfile.ZIP_DEFLATED) as target:
        target.writestr("manifest.json", json.dumps(manifest))
        target.writestr("basemap.mbtiles", mbtiles)

    response = client.post(
        "/api/map-bundles/import",
        files={"file": ("invalid.zip", malformed.getvalue(), "application/zip")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "地图包来源清单不完整或不符合规范"
    assert db_session.query(PublicMapBundle).count() == 0


@pytest.mark.parametrize(
    ("bundle_kwargs", "expected_detail"),
    [
        ({"include_tile": False}, "离线瓦片包没有可用瓦片"),
        ({"tile": None}, "离线瓦片文件无效"),
        ({"tile": b"not-an-image"}, "离线瓦片格式不受支持"),
        ({"tile": b"\x89PNG\r\n\x1a\ntruncated"}, "离线瓦片图片已损坏或被截断"),
    ],
)
def test_import_rejects_empty_or_corrupt_tile_sets(
    client: TestClient,
    db_session: Session,
    tmp_path,
    bundle_kwargs,
    expected_detail,
):
    response = client.post(
        "/api/map-bundles/import",
        files={
            "file": (
                "invalid-tiles.zip",
                _bundle_bytes(tmp_path, bundle_id=str(uuid4()), **bundle_kwargs),
                "application/zip",
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == expected_detail
    assert db_session.query(PublicMapBundle).count() == 0


@pytest.mark.parametrize(
    ("bounds", "tile_coordinate"),
    [
        ([124.0, 46.0, 126.0, 47.0], (2, 0, 0)),
        ([0.0, -10.0, 10.0, 10.0], (1, 1, 0)),
    ],
)
def test_import_rejects_tiles_that_do_not_fully_cover_the_declared_bounds(
    client: TestClient,
    db_session: Session,
    tmp_path,
    bounds,
    tile_coordinate,
):
    response = client.post(
        "/api/map-bundles/import",
        files={
            "file": (
                "wrong-tile-coverage.zip",
                _bundle_bytes(
                    tmp_path,
                    bundle_id="wrong-tile-coverage",
                    bounds=bounds,
                    tile_coordinate=tile_coordinate,
                ),
                "application/zip",
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "离线瓦片未覆盖清单声明的地域范围"
    assert db_session.query(PublicMapBundle).count() == 0


def test_manifest_attribution_is_escaped_before_leaflet_renders_it(
    client: TestClient,
    db_session: Session,
    tmp_path,
):
    area = _default_area(db_session)
    bundle = client.post(
        "/api/map-bundles/import",
        files={
            "file": (
                "escaped-attribution.zip",
                _bundle_bytes(
                    tmp_path,
                    bundle_id="escaped-attribution",
                    attribution='<img src=x onerror="alert(1)">',
                ),
                "application/zip",
            )
        },
    ).json()
    snapshot = client.post(
        "/api/map-snapshots/build",
        json={"operational_area_id": area.id, "public_bundle_id": bundle["id"]},
    ).json()
    assert client.post(f"/api/map-snapshots/{snapshot['id']}/publish").status_code == 200

    manifest = client.get(f"/api/maps/{snapshot['id']}/manifest").json()

    assert "<img" not in manifest["attribution"]
    assert manifest["attribution"].startswith("&lt;img")


def test_failed_new_build_keeps_previous_current_snapshot(client: TestClient, db_session: Session, tmp_path):
    area = _default_area(db_session)
    first_bundle = _import_bundle(client, tmp_path, bundle_id="public-v1")
    first = client.post(
        "/api/map-snapshots/build",
        json={"operational_area_id": area.id, "public_bundle_id": first_bundle["id"]},
    ).json()
    assert client.post(f"/api/map-snapshots/{first['id']}/publish").status_code == 200

    missing = client.post(
        "/api/map-snapshots/build",
        json={"operational_area_id": area.id, "public_bundle_id": 999999},
    )

    assert missing.status_code == 404
    current = client.get("/api/maps/current/manifest")
    assert current.status_code == 200
    assert current.json()["snapshot_id"] == first["id"]


def test_map_snapshot_can_roll_back_to_previous_version(client: TestClient, db_session: Session, tmp_path):
    area = _default_area(db_session)
    snapshots = []
    for version in ("public-v1", "public-v2"):
        bundle = _import_bundle(client, tmp_path, bundle_id=version)
        snapshot = client.post(
            "/api/map-snapshots/build",
            json={"operational_area_id": area.id, "public_bundle_id": bundle["id"]},
        ).json()
        assert client.post(f"/api/map-snapshots/{snapshot['id']}/publish").status_code == 200
        snapshots.append(snapshot)

    rolled_back = client.post(f"/api/map-snapshots/{snapshots[0]['id']}/rollback")

    assert rolled_back.status_code == 200
    assert rolled_back.json()["status"] == "current"
    current = client.get("/api/maps/current/manifest").json()
    assert current["snapshot_id"] == snapshots[0]["id"]


def test_public_map_publish_and_rollback_preserve_verified_internal_roads(client, db_session, tmp_path):
    from app.models.map_foundation import MapSource
    from app.models.user import User
    from test_map_foundation import _client
    from test_internal_road_import import collection, feature

    area = _default_area(db_session)
    db_session.add(User(id=1, username='internal-road-test', password_hash='not-a-login',
        display_name='合成测试管理员', role='admin', is_active=True))
    db_session.add(MapSource(id=1, source_key='private-roads', name='内部道路',
        source_type='internal_gis', operational_area_id=area.id))
    db_session.commit()
    db_session.info['authorized_area_ids'] = (area.id,)
    db_session.info['area_access_levels'] = {area.id: 'manage'}
    roads = _client(db_session)
    base = '/api/map-sources/1/roads'
    road = feature()
    road['properties']['conditions'] = {'gate': 'closed'}
    imported = roads.post(base + '/ingest', json=collection(road))
    assert imported.status_code == 201
    batch = imported.json()
    review = roads.post(f"{base}/imports/{batch['id']}/features/road-1/reviews", json={
        'input_sha256': batch['input_sha256'], 'request_key': 'public-update-001',
        'decision': 'verified', 'note': '合成内部资料', 'evidence_reference': '合成台账第1页'})
    assert review.status_code == 201
    baseline = roads.get(base + '/catalog').json()
    original_batch = roads.get(f"{base}/imports/{batch['id']}").json()
    assert baseline['items'][0]['last_verified_import_id'] == batch['id']
    snapshots = []
    for version in ('public-road-test-v1', 'public-road-test-v2'):
        bundle = _import_bundle(client, tmp_path, bundle_id=version)
        built = client.post('/api/map-snapshots/build', json={
            'operational_area_id': area.id, 'public_bundle_id': bundle['id']})
        assert built.status_code == 201
        snapshot_id = built.json()['id']
        assert client.post(f'/api/map-snapshots/{snapshot_id}/publish').status_code == 200
        assert client.get('/api/maps/current/manifest').json()['snapshot_id'] == snapshot_id
        assert roads.get(base + '/catalog').json() == baseline
        assert roads.get(f"{base}/imports/{batch['id']}").json() == original_batch
        snapshots.append(snapshot_id)
    assert client.post(f'/api/map-snapshots/{snapshots[0]}/rollback').status_code == 200
    assert roads.get(base + '/catalog').json() == baseline
    assert roads.get(f"{base}/imports/{batch['id']}").json() == original_batch


def test_snapshot_layers_freeze_production_features(client: TestClient, db_session: Session, tmp_path):
    area = _default_area(db_session)
    asset = JurisdictionAsset(
        operational_area_id=area.id,
        canonical_key="well:frozen",
        name="冻结前井场",
        asset_type="well",
        latitude=46.61,
        longitude=125.11,
        source="ledger",
        verified=True,
        verification_state="source_verified",
        status="active",
        attributes={"production_output": 88},
    )
    db_session.add(asset)
    db_session.commit()
    bundle = _import_bundle(client, tmp_path, bundle_id="public-frozen")
    built = client.post(
        "/api/map-snapshots/build",
        json={"operational_area_id": area.id, "public_bundle_id": bundle["id"]},
    ).json()
    assert client.post(f"/api/map-snapshots/{built['id']}/publish").status_code == 200

    asset.name = "冻结后改名"
    asset.latitude = 47.0
    db_session.commit()

    layers = client.get(f"/api/maps/{built['id']}/layers")
    assert layers.status_code == 200
    feature = layers.json()["features"][0]
    assert feature["properties"]["name"] == "冻结前井场"
    assert feature["geometry"]["coordinates"] == [125.11, 46.61]
    frozen = db_session.query(MapSnapshotFeature).one()
    assert frozen.asset_id == asset.id

    original_asset_id = asset.id
    db_session.delete(asset)
    db_session.commit()
    db_session.expire_all()

    preserved = db_session.query(MapSnapshotFeature).one()
    assert preserved.asset_id == original_asset_id
    assert preserved.name == "冻结前井场"


def test_snapshot_layers_can_filter_evidence_assets_and_enforce_response_limit(
    client: TestClient,
    db_session: Session,
    tmp_path,
):
    area = _default_area(db_session)
    assets = [
        JurisdictionAsset(
            operational_area_id=area.id,
            canonical_key=f"well:filtered-{index}",
            name=f"候选设施{index}",
            asset_type="well",
            latitude=46.61 + index * 0.001,
            longitude=125.11 + index * 0.001,
            source="ledger",
            verified=True,
            verification_state="source_verified",
            status="active",
        )
        for index in range(2)
    ]
    db_session.add_all(assets)
    db_session.commit()
    bundle = _import_bundle(client, tmp_path, bundle_id="public-filtered")
    built = client.post(
        "/api/map-snapshots/build",
        json={"operational_area_id": area.id, "public_bundle_id": bundle["id"]},
    ).json()
    assert client.post(f"/api/map-snapshots/{built['id']}/publish").status_code == 200

    filtered = client.get(
        f"/api/maps/{built['id']}/layers",
        params={"asset_ids": str(assets[1].id), "limit": 10},
    )
    assert filtered.status_code == 200
    assert [item["properties"]["asset_id"] for item in filtered.json()["features"]] == [assets[1].id]
    assert filtered.json()["truncated"] is False

    limited = client.get(f"/api/maps/{built['id']}/layers", params={"limit": 1})
    assert limited.status_code == 200
    assert len(limited.json()["features"]) == 1
    assert limited.json()["truncated"] is True


def test_wrong_region_bundle_cannot_replace_the_current_snapshot(
    client: TestClient,
    db_session: Session,
    tmp_path,
):
    area = _default_area(db_session)
    first_bundle = _import_bundle(client, tmp_path, bundle_id="public-covered")
    first = client.post(
        "/api/map-snapshots/build",
        json={"operational_area_id": area.id, "public_bundle_id": first_bundle["id"]},
    ).json()
    assert client.post(f"/api/map-snapshots/{first['id']}/publish").status_code == 200

    wrong_bundle_response = client.post(
        "/api/map-bundles/import",
        files={
            "file": (
                "wrong-region.zip",
                _bundle_bytes(
                    tmp_path,
                    bundle_id="public-wrong-region",
                    bounds=[80.0, 20.0, 81.0, 21.0],
                ),
                "application/zip",
            )
        },
    )
    assert wrong_bundle_response.status_code == 201

    rejected = client.post(
        "/api/map-snapshots/build",
        json={
            "operational_area_id": area.id,
            "public_bundle_id": wrong_bundle_response.json()["id"],
        },
    )

    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "地图包范围未完整覆盖厂区"
    current = client.get("/api/maps/current/manifest")
    assert current.status_code == 200
    assert current.json()["snapshot_id"] == first["id"]


def test_map_health_degrades_when_another_active_area_has_no_snapshot(
    client: TestClient,
    db_session: Session,
    tmp_path,
):
    area = _default_area(db_session)
    bundle = _import_bundle(client, tmp_path, bundle_id="public-health")
    snapshot = client.post(
        "/api/map-snapshots/build",
        json={"operational_area_id": area.id, "public_bundle_id": bundle["id"]},
    ).json()
    assert client.post(f"/api/map-snapshots/{snapshot['id']}/publish").status_code == 200
    db_session.add(
        OperationalArea(
            code="area-without-map",
            name="缺少地图的厂区",
            status="active",
            is_default=False,
        )
    )
    db_session.commit()

    health = OfflineMapService.health(db_session)

    assert health["status"] == "degraded"
    assert health["active_area_count"] == 2
    assert health["ready_area_count"] == 1
    assert health["missing_area_count"] == 1


def test_truncated_map_artifact_cannot_publish_and_degrades_health(
    client: TestClient,
    db_session: Session,
    tmp_path,
):
    area = _default_area(db_session)
    first_bundle = _import_bundle(client, tmp_path, bundle_id="artifact-v1")
    first = client.post(
        "/api/map-snapshots/build",
        json={"operational_area_id": area.id, "public_bundle_id": first_bundle["id"]},
    ).json()
    assert client.post(f"/api/map-snapshots/{first['id']}/publish").status_code == 200

    second_bundle = _import_bundle(client, tmp_path, bundle_id="artifact-v2")
    second = client.post(
        "/api/map-snapshots/build",
        json={"operational_area_id": area.id, "public_bundle_id": second_bundle["id"]},
    ).json()
    second_artifact = OfflineMapService._bundle_artifact(db_session, second_bundle["id"])
    assert second_artifact is not None
    OfflineMapService._storage_path(second_artifact.storage_key).write_bytes(b"truncated")

    rejected = client.post(f"/api/map-snapshots/{second['id']}/publish")

    assert rejected.status_code == 503
    current = client.get("/api/maps/current/manifest")
    assert current.json()["snapshot_id"] == first["id"]

    first_artifact = OfflineMapService._bundle_artifact(db_session, first_bundle["id"])
    assert first_artifact is not None
    OfflineMapService._storage_path(first_artifact.storage_key).write_bytes(b"truncated")
    health = OfflineMapService.health(db_session)
    assert health["status"] == "degraded"
    assert health["ready_area_count"] == 0


def test_same_size_map_artifact_corruption_degrades_health(
    client: TestClient,
    db_session: Session,
    tmp_path,
):
    area = _default_area(db_session)
    bundle = _import_bundle(client, tmp_path, bundle_id="artifact-same-size")
    snapshot = client.post(
        "/api/map-snapshots/build",
        json={"operational_area_id": area.id, "public_bundle_id": bundle["id"]},
    ).json()
    assert client.post(f"/api/map-snapshots/{snapshot['id']}/publish").status_code == 200
    artifact = OfflineMapService._bundle_artifact(db_session, bundle["id"])
    assert artifact is not None
    path = OfflineMapService._storage_path(artifact.storage_key)
    content = bytearray(path.read_bytes())
    tile_offset = content.find(VALID_PNG_TILE)
    assert tile_offset >= 0
    content[tile_offset + 30] ^= 1
    path.write_bytes(content)
    assert path.stat().st_size == artifact.size_bytes

    health = OfflineMapService.health(db_session)

    assert health["status"] == "degraded"
    assert health["ready_area_count"] == 0


def test_same_public_bundle_only_reanalyzes_affected_spatial_grids():
    previous = SimpleNamespace(
        public_bundle_id=1,
        manifest={"production_grid_hashes": {"46.60:125.10": "old", "47.00:126.00": "same"}},
    )
    current = SimpleNamespace(
        public_bundle_id=1,
        manifest={"production_grid_hashes": {"46.60:125.10": "new", "47.00:126.00": "same"}},
    )

    affected = OfflineMapService._affected_grids(previous, current)

    assert "46.60:125.10" in affected
    assert "46.70:125.20" in affected
    assert "47.00:126.00" not in affected


def test_new_public_bundle_unions_public_and_production_changed_grids():
    previous = SimpleNamespace(
        public_bundle_id=1,
        manifest={"production_grid_hashes": {"46.60:125.10": "old"}},
    )
    current = SimpleNamespace(
        public_bundle_id=2,
        manifest={
            "public_bundle_changed_grids": ["46.70:125.20"],
            "production_grid_hashes": {"46.60:125.10": "new"},
        },
    )

    affected = OfflineMapService._affected_grids(previous, current)

    assert "46.60:125.10" in affected
    assert "46.70:125.20" in affected


def test_unlocated_asset_changes_snapshot_watermark_without_spatial_reanalysis():
    asset = JurisdictionAsset(
        id=77,
        name="待补坐标井",
        asset_type="well",
        latitude=None,
        longitude=None,
        status="active",
        source="ledger",
        attributes={"production_output": 80},
    )
    first = OfflineMapService._production_grid_hashes([asset])
    asset.attributes = {"production_output": 90}
    second = OfflineMapService._production_grid_hashes([asset])

    assert first["__unlocated__"] != second["__unlocated__"]
    previous = SimpleNamespace(public_bundle_id=1, manifest={"production_grid_hashes": first})
    current = SimpleNamespace(public_bundle_id=1, manifest={"production_grid_hashes": second})
    assert OfflineMapService._affected_grids(previous, current) == set()
