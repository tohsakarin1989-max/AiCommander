import hashlib
import io
import math
import os

import pytest
from PIL import Image, ImageDraw

from app.config import settings
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapPackageArtifact, MapSnapshot, MapSnapshotFeature
from app.services.case_map_image import CaseMapImageError, render_case_map_image
from app.services.case_result_access import CaseResultAccessError
from app.services.case_result_service import CaseResultService
from test_case_results import db_session, prepare, result_data  # noqa: F401
from tests.test_offline_maps import _mbtiles_bytes


@pytest.mark.skipif(os.environ.get("AIC_TEST_MAP_BROWSER") != "1", reason="requires explicit real browser rendering")
@pytest.mark.parametrize("failure", [None, "missing_tile", "invalid_region", "revoked_after_render"])
def test_real_browser_renders_registered_offline_raster(db_session, result_data, tmp_path, monkeypatch, failure):
    prepare(db_session)
    monkeypatch.setattr(settings, "MAP_PACKAGE_ROOT", str(tmp_path))
    tile = Image.new("RGB", (256, 256), "#d5e3d0")
    draw = ImageDraw.Draw(tile)
    draw.line([(0, 82), (256, 82)], fill="#ffffff", width=5)
    draw.line([(128, 0), (128, 256)], fill="#7299bb", width=8)
    buffer = io.BytesIO()
    tile.save(buffer, format="PNG")
    bounds = [3471 / 4096 * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * 1448 / 4096)))),
              3472 / 4096 * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * 1447 / 4096))))]
    payload = _mbtiles_bytes(tmp_path, buffer.getvalue(), tile_coordinate=(12, 3471, 2648), bounds=bounds,
                             include_tile=failure != "missing_tile")
    path = tmp_path / "synthetic.mbtiles"
    path.write_bytes(payload)
    db_session.add(MapPackageArtifact(public_bundle_id=1, artifact_kind="mbtiles", storage_key=path.name,
        sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload)))
    db_session.execute(MapSnapshot.__table__.update().values(manifest={
        "min_zoom": 12, "max_zoom": 12, "bounds": bounds,
    }))
    profile, _, candidate = result_data
    profile.payload = {**profile.payload, "analysis_facts": {"latitude": 46.6, "longitude": 125.1}}
    candidate.region = {"type": "circle", "center": [125.1, 46.6], "radius_m": 1000}
    if failure == "invalid_region":
        candidate.region = {"type": "circle", "center": [None, 46.6], "radius_m": 1000}
    db_session.execute(MapSnapshotFeature.__table__.update().values(latitude=46.61, longitude=125.11))
    db_session.commit()
    saved, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    if failure == "revoked_after_render":
        from playwright.sync_api import Page

        screenshot = Page.screenshot

        def revoke_after_screenshot(page, **kwargs):
            image = screenshot(page, **kwargs)
            db_session.execute(JurisdictionAsset.__table__.update().values(operational_area_id=2))
            db_session.commit()
            return image

        monkeypatch.setattr(Page, "screenshot", revoke_after_screenshot)
        with pytest.raises(CaseResultAccessError):
            render_case_map_image(db_session, saved["id"])
        return
    if failure:
        with pytest.raises(CaseMapImageError, match="^map_render_failed$"):
            render_case_map_image(db_session, saved["id"])
        return
    image = render_case_map_image(db_session, saved["id"])
    (tmp_path / "rendered-map.png").write_bytes(image)
    decoded = Image.open(io.BytesIO(image)).convert("RGB")
    assert decoded.width == 960 and decoded.height >= 700
    colors = decoded.getcolors(decoded.width * decoded.height)
    assert any(count > 10000 and color == (213, 227, 208) for count, color in colors)
    assert any(count > 30 and color == (220, 38, 38) for count, color in colors)
    assert any(count > 100 and color == (114, 153, 187) for count, color in colors)
