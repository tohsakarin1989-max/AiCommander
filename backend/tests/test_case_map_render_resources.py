import pytest

from app.models.jurisdiction import JurisdictionAsset
from app.services import case_map_render_resources as resources
from app.services.case_result_access import CaseResultAccessError
from app.services.case_result_service import CaseResultService
from test_case_results import db_session, prepare, result_data  # noqa: F401


@pytest.mark.parametrize("url", [
    "https://example.org/api/maps/map-1/style.json", "http://aic-map.invalid/api/maps/map-1/style.json",
    "file:///etc/passwd", "https://aic-map.invalid@evil.test/api/maps/map-1/style.json",
    "https://aic-map.invalid:443/api/maps/map-1/style.json", "https://aic-map.invalid/api/maps/current/style.json",
    "https://aic-map.invalid/api/maps/map-2/style.json", "https://aic-map.invalid/api/cases/1",
    "https://aic-map.invalid/api/maps/map-1/style.json?url=https://example.org",
    "https://aic-map.invalid/api/maps/map-1/%252e%252e/style.json",
    "https://aic-map.invalid/api/maps/map-1/%2e%2e/style.json",
    "https://aic-map.invalid/api/maps/tiles/map-1/23/1/1",
    "https://aic-map.invalid/api/maps/tiles/map-1/1/2/1",
    "\nhttps://aic-map.invalid/api/maps/map-1/style.json",
    "https://aic-map.invalid/api/maps/map-1/sty\tle.json",
    "https://[broken/api/maps/map-1/style.json",
    "https://aic-map.invalid/api/maps/map-1/glyphs/%ff/0-255.pbf",
])
def test_only_pinned_local_map_resources_are_allowed(url):
    with pytest.raises(resources.MapRenderResourceError):
        resources._resource_request(url, "map-1")


def test_valid_resource_routes_do_not_interpret_urls_as_files():
    root = resources.RENDER_ORIGIN
    assert resources._resource_request(root + "/api/maps/map-1/style.json", "map-1") == ("style", ())
    assert resources._resource_request(root + "/api/maps/map-1/sprite@2x.png", "map-1") == ("sprite", ("@2x.png",))
    assert resources._resource_request(root + "/api/maps/map-1/glyphs/Noto%20Sans/0-255.pbf", "map-1") == ("glyph", ("Noto Sans", "0-255"))
    assert resources._resource_request(root + "/api/maps/tiles/map-1/6/1/2", "map-1") == ("tile", (6, 1, 2))


@pytest.fixture
def authorized_reader(db_session, result_data):
    prepare(db_session)
    saved, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    return resources.CaseMapRenderResources(db_session, saved["id"])


def test_read_dispatches_pinned_snapshot_and_revocation_blocks_bytes(authorized_reader, db_session, monkeypatch):
    calls = []

    def read_tile(db, snapshot, *args):
        calls.append((snapshot, args))
        return b"synthetic-tile", "image/png"

    monkeypatch.setattr(resources.OfflineMapService, "read_tile", read_tile)
    url = resources.RENDER_ORIGIN + "/api/maps/tiles/map-1/6/1/2"
    assert authorized_reader.read(url) == (b"synthetic-tile", "image/png")
    assert calls == [("map-1", (6, 1, 2))]
    db_session.execute(JurisdictionAsset.__table__.update().values(operational_area_id=2))
    db_session.commit()
    with pytest.raises(CaseResultAccessError):
        authorized_reader.read(url)
    assert len(calls) == 1


def test_request_and_byte_budgets_fail_closed(authorized_reader, monkeypatch):
    monkeypatch.setattr(resources, "MAX_REQUESTS", 2)
    for _ in range(2):
        with pytest.raises(resources.MapRenderResourceError, match="denied"):
            authorized_reader.read("https://example.org")
    with pytest.raises(resources.MapRenderResourceError, match="budget_exceeded"):
        authorized_reader.read(resources.RENDER_ORIGIN + "/api/maps/map-1/style.json")
    authorized_reader.requests = 0
    monkeypatch.setattr(resources, "MAX_RESOURCE_BYTES", 3)
    monkeypatch.setattr(resources, "read_sprite", lambda *args: (b"oversized", "image/png"))
    with pytest.raises(resources.MapRenderResourceError, match="budget_exceeded"):
        authorized_reader.read(resources.RENDER_ORIGIN + "/api/maps/map-1/sprite.png")


def test_real_mbtiles_read_uses_historical_snapshot_and_xyz_conversion(
    authorized_reader, db_session, tmp_path, monkeypatch,
):
    import hashlib

    from app.config import settings
    from app.models.map_foundation import MapPackageArtifact, MapSnapshot
    from tests.test_offline_maps import VALID_PNG_TILE, _mbtiles_bytes

    monkeypatch.setattr(settings, "MAP_PACKAGE_ROOT", str(tmp_path))
    payload = _mbtiles_bytes(tmp_path, tile_coordinate=(6, 54, 42))
    path = tmp_path / "historical.mbtiles"
    path.write_bytes(payload)
    db_session.add(MapPackageArtifact(
        public_bundle_id=1, artifact_kind="mbtiles", storage_key=path.name,
        sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload),
    ))
    db_session.execute(MapSnapshot.__table__.update().values(status="superseded"))
    db_session.add(MapSnapshot(
        id="map-new", version="new", operational_area_id=1, public_bundle_id=1,
        status="current", manifest={}, feature_watermark="new",
    ))
    db_session.commit()
    url = resources.RENDER_ORIGIN + "/api/maps/tiles/map-1/6/54/21"
    assert authorized_reader.read(url) == (VALID_PNG_TILE, "image/png")
    assert authorized_reader.bytes_read == len(VALID_PNG_TILE)
    with pytest.raises(resources.MapRenderResourceError, match="resource_unavailable"):
        authorized_reader.read(url[:-2] + "22")
    # 损坏存储不能改用current或返回先前缓存的图片。
    path.write_bytes(b"broken sqlite")
    with pytest.raises(resources.MapRenderResourceError, match="^map_render_resource_unavailable$"):
        authorized_reader.read(url)
