import hashlib
import io
import math
import os
from zipfile import ZipFile

import pytest
from PIL import Image, ImageDraw

from app.config import settings
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapPackageArtifact, MapSnapshot, MapSnapshotFeature
from app.services.case_map_image import CaseMapImageError, render_case_map_image
from app.services.case_result_access import CaseResultAccessError
from app.services.case_result_service import CaseResultService
from test_case_results import db_session, prepare, result_data  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from tests.test_offline_maps import _mbtiles_bytes


@pytest.mark.skipif(os.environ.get("AIC_TEST_MAP_BROWSER") != "1", reason="requires explicit real browser rendering")
@pytest.mark.parametrize("failure", [None, "missing_tile", "invalid_region", "revoked_after_render", "saved_road"])
def test_real_browser_renders_registered_offline_raster(db_session, result_data, tmp_path, monkeypatch, failure, request):
    if failure == 'saved_road':
        request.getfixturevalue('ready')
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
    if failure and failure != 'saved_road':
        with pytest.raises(CaseMapImageError, match="^map_render_failed$"):
            render_case_map_image(db_session, saved["id"])
        return
    from app.services.case_result_export import export_case_result_docx

    artifact_id = None
    if failure == 'saved_road':
        from app.services.case_road_artifact_service import freeze_road_artifact
        from test_road_access_policy import AT

        def encode_deltas(values):
            encoded = ''
            for value in values:
                value = value << 1 if value >= 0 else ~(value << 1)
                while value >= 32:
                    encoded += chr((32 | (value & 31)) + 63)
                    value >>= 5
                encoded += chr(value + 63)
            return encoded
        road = {'schema_version': 'case-road-route-4.2.0-1', 'result_id': saved['id'],
            'content_sha256': saved['content_sha256'], 'map_snapshot_id': 'map-1',
            'target': {'asset_id': 1, 'name': '合成设施'}, 'boundary': '合成留存路径，不是实际轨迹',
            'route': {'network_id': 'graph-1', 'graph_sha256': 'c' * 64, 'policy_revision': 1,
                'analysis_at': AT.isoformat(), 'vehicle': {'kind': 'auto', 'source': 'explicit_reference_assumption'},
                'distance_m': 1350, 'shape_polyline6': encode_deltas([46600000, 125100000, 10000, 10000])}}
        artifact_id = freeze_road_artifact(db_session, road)['id']
        db_session.commit()
    document, data = export_case_result_docx(db_session, saved["id"], road_artifact_id=artifact_id)
    assert document.content_sha256 == saved["content_sha256"]
    (tmp_path / "map-result.docx").write_bytes(data)
    with ZipFile(io.BytesIO(data)) as archive:
        media = [name for name in archive.namelist() if name.startswith("word/media/") and not name.endswith("/")]
        assert len(media) == 1
        image = archive.read(media[0])
        xml = archive.read("word/document.xml").decode()
        assert "map-1" in xml and "冻结版本地图" in xml
        assert 'TargetMode="External"' not in archive.read("word/_rels/document.xml.rels").decode()
    (tmp_path / "rendered-map.png").write_bytes(image)
    decoded = Image.open(io.BytesIO(image)).convert("RGB")
    assert decoded.width == 960 and decoded.height >= 700
    colors = decoded.getcolors(decoded.width * decoded.height)
    assert any(count > 10000 and color == (213, 227, 208) for count, color in colors)
    assert any(count > 30 and color == (220, 38, 38) for count, color in colors)
    assert any(count > 100 and color == (114, 153, 187) for count, color in colors)
    if failure == 'saved_road':
        assert '道路参考分析（历史留存）' in xml and '1.35 公里' in xml
        assert document.road_artifact_id == artifact_id
        assert any(count > 150 and color == (3, 105, 161) for count, color in colors)
        print(f'road_document_artifacts={tmp_path}')
        if os.environ.get('AIC_TEST_PDF_OFFICE') == '1':
            from app.services.case_result_pdf import export_case_result_pdf
            pdf_document, pdf = export_case_result_pdf(db_session, saved['id'], road_artifact_id=artifact_id)
            assert pdf_document.road_artifact_sha256 == document.road_artifact_sha256
            assert pdf.startswith(b'%PDF-')
            (tmp_path / 'road-result.pdf').write_bytes(pdf)
