"""Real public assets + synthetic case, never a production DB or release gate bypass."""
import io
import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image

from app.config import settings
from app.models.map_foundation import MapPackageArtifact, MapSnapshot, MapSnapshotFeature, PublicMapBundle
from app.services.case_map_render_resources import CaseMapRenderResources
from app.services.case_result_export import export_case_result_docx
from app.services.case_result_service import CaseResultService
from app.services.map_asset_layout import storage_key
from app.services.map_package_install import install_assets
from test_case_results import db_session, prepare, result_data  # noqa: F401


@pytest.mark.skipif(os.environ.get("AIC_TEST_REAL_VECTOR_MAP") != "1", reason="requires fixed public map assets and browser")
@pytest.mark.parametrize("longitude,latitude", [(125.03, 46.6), (123.95, 47.34)], ids=["daqing", "qiqihar"])
def test_real_two_city_vector_map_and_chinese_glyphs_in_word(db_session, result_data, tmp_path, monkeypatch, longitude, latitude):
    repository = Path(__file__).resolve().parents[2]
    assembly = repository / "backups/map-foundation/v4-source/20260908/complete-candidate-v2/map-assembly-muyp0orr"
    assert assembly.is_dir(), "真实公共资产缺失，不能计入验收"
    root = tmp_path / "maps"
    root.mkdir()
    installed = install_assets(assembly, root)
    assert installed["status"] == "installed_integrity_verified"
    manifest = json.loads((assembly / "manifest.json").read_text())
    assert installed["package_hash"] == "d4ab1cf9b73f4352b437f81939aed2a86f2afd313fc12185690bb3af772ede48"
    monkeypatch.setattr(settings, "MAP_PACKAGE_ROOT", str(root))
    prepare(db_session)
    # Only the disposable fixture is registered here. This test checks export, not import/publication acceptance.
    bundle = db_session.get(PublicMapBundle, 1)
    bundle.manifest = manifest
    bundle.package_hash = installed["package_hash"]
    bundle.bundle_id = manifest["bundle_id"]
    bundle.provider, bundle.source_version = manifest["provider"], manifest["source_version"]
    bundle.license_record, bundle.bounds, bundle.status = manifest["license"], manifest["bounds"], "accepted"
    for asset in manifest["assets"]:
        db_session.add(MapPackageArtifact(public_bundle_id=1,
            artifact_kind="mbtiles" if asset["role"] == "vector" else asset["role"],
            storage_key=storage_key(bundle.package_hash, asset, manifest),
            sha256=asset["sha256"], size_bytes=asset["size_bytes"]))
    snapshot_id = "f6847955-4cf7-4abd-a944-d9931d51c9b2"
    db_session.execute(MapSnapshot.__table__.update().values(status="superseded"))
    db_session.add(MapSnapshot(id=snapshot_id, version="public-vector-export-fixture", operational_area_id=1,
        public_bundle_id=1, manifest={"bounds": manifest["bounds"]}, feature_watermark="fixture", status="current"))
    db_session.flush()
    profile, run, candidate = result_data
    run.map_snapshot_id = snapshot_id
    candidate.evidence_refs = [ref.replace("@snapshot:map-1", "@snapshot:" + snapshot_id)
                               for ref in candidate.evidence_refs]
    profile.payload = {**profile.payload, "analysis_facts": {"latitude": latitude, "longitude": longitude}}
    candidate.region = {"type": "circle", "center": [longitude, latitude], "radius_m": 3000}
    db_session.execute(MapSnapshotFeature.__table__.update().values(
        snapshot_id=snapshot_id, latitude=latitude + 0.01, longitude=longitude + 0.01))
    db_session.commit()
    saved, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    requests = []
    real_read = CaseMapRenderResources.read

    def tracked_read(reader, url):
        result = real_read(reader, url)
        requests.append(url)
        return result

    monkeypatch.setattr(CaseMapRenderResources, "read", tracked_read)
    document, data = export_case_result_docx(db_session, saved["id"])
    assert document.content_sha256 == saved["content_sha256"]
    assert any(url.endswith("/style.json") for url in requests)
    assert any("/glyphs/" in url for url in requests)
    assert any("/tiles/" in url for url in requests)
    assert all(url.startswith("https://aic-map.invalid/") for url in requests)
    with ZipFile(io.BytesIO(data)) as archive:
        images = [name for name in archive.namelist() if name.startswith("word/media/") and name.endswith(".png")]
        assert len(images) == 1
        image = archive.read(images[0])
    pixels = Image.open(io.BytesIO(image)).convert("RGB")
    assert pixels.width == 960 and pixels.height >= 700
    assert len(pixels.getcolors(pixels.width * pixels.height)) > 1000
    (tmp_path / "real-vector-result.docx").write_bytes(data)
    (tmp_path / "real-vector-map.png").write_bytes(image)
    (tmp_path / "resource-counts.json").write_text(json.dumps({
        "tiles": sum("/tiles/" in url for url in requests),
        "glyphs": sum("/glyphs/" in url for url in requests),
        "manifest_sha256": installed["package_hash"],
        "synthetic_case": True,
    }))
