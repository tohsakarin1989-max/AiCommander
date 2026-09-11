"""Real public assets + synthetic case, never a production DB or release gate bypass."""
import io
import json
import os
import shutil
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
from test_road_network_service import ready  # noqa: F401


def _automatic_road_report(db, profile, run, root):
    """Real services/native worker; synthetic scope and upstream profile fixture."""
    from sqlalchemy import select
    from app.models.case_pipeline import OutboxEvent
    from app.models.road_network import RoadNetworkVersion
    from app.services import case_road_triggers, case_road_jobs
    from app.services.case_road_artifact_service import read_road_artifact, freeze_road_artifact
    from app.services.case_road_comparison import route_result_target
    from app.services.case_road_vehicle import frozen_road_vehicle
    from app.services.road_graph_artifact import graph_inventory_sha256, install_graph_artifact
    from test_case_road_triggers import source_event
    from datetime import datetime

    graph_path = Path(os.environ['AIC_TEST_ROAD_GRAPH']).resolve(strict=True)
    digest = graph_inventory_sha256(graph_path)
    install_graph_artifact(graph_path, root / 'road-graphs', expected_sha256=digest)
    graph = db.get(RoadNetworkVersion, 'graph-1')
    graph.engine_version, graph.graph_sha256, graph.artifact_key = '3.8.3', digest, digest
    db.commit()
    source_event(db, profile)
    result_id, _ = CaseResultService.freeze_completed_inputs(db, profile, run)
    db.commit()
    request_id = db.scalar(select(OutboxEvent.id).where(OutboxEvent.event_type == case_road_triggers.REQUEST_TYPE))
    handoff = case_road_triggers.process_request(db, request_id)
    assert handoff['status'] == 'completed', handoff
    job_id = db.scalar(select(OutboxEvent.id).where(OutboxEvent.event_type == case_road_jobs.EVENT_TYPE))
    calculated = case_road_jobs.process_comparison(db, job_id, artifact_root=root / 'road-graphs')
    assert calculated['outcome'] == 'calculated', calculated
    comparison = read_road_artifact(db, calculated['artifact']['id'])['content']
    matrix = comparison['matrix']
    assert 600 < matrix['cells'][0]['distance_m'] < 800
    saved = CaseResultService.read(db, result_id)
    route = route_result_target(db, result_id=result_id, asset_id=comparison['targets'][0]['asset_id'],
        network_id=matrix['network_id'], graph_sha256=digest, content_sha256=saved['content_sha256'],
        analysis_at=datetime.fromisoformat(matrix['analysis_at']),
        vehicle=frozen_road_vehicle(saved['content']), artifact_root=root / 'road-graphs')
    artifact = freeze_road_artifact(db, route)
    db.commit()
    return saved, artifact


@pytest.mark.skipif(os.environ.get("AIC_TEST_REAL_VECTOR_MAP") != "1", reason="requires fixed public map assets and browser")
@pytest.mark.parametrize("longitude,latitude", [(125.03, 46.6), (123.95, 47.34)], ids=["daqing", "qiqihar"])
def test_real_two_city_vector_map_and_chinese_glyphs_in_word(db_session, result_data, tmp_path, monkeypatch, longitude, latitude, request):
    road_mode = bool(os.environ.get('AIC_TEST_ROAD_GRAPH'))
    if road_mode:
        assert longitude == 125.03, 'road integration fixture is Daqing only'
        request.getfixturevalue('ready')
        longitude, latitude = 125.1852727, 46.54446175
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
        snapshot_id=snapshot_id, latitude=46.5444392 if road_mode else latitude + 0.01,
        longitude=125.18509545 if road_mode else longitude + 0.01))
    db_session.commit()
    road_artifact = None
    if road_mode:
        saved, road_artifact = _automatic_road_report(db_session, profile, run, root)
    else:
        saved, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    requests = []
    real_read = CaseMapRenderResources.read

    def tracked_read(reader, url):
        result = real_read(reader, url)
        requests.append(url)
        return result

    monkeypatch.setattr(CaseMapRenderResources, "read", tracked_read)
    artifact_id = road_artifact['id'] if road_artifact else None
    document, data = export_case_result_docx(db_session, saved["id"], road_artifact_id=artifact_id)
    assert document.content_sha256 == saved["content_sha256"]
    assert any(url.endswith("/style.json") for url in requests)
    assert any("/glyphs/" in url for url in requests)
    assert any("/tiles/" in url for url in requests)
    assert all(url.startswith("https://aic-map.invalid/") for url in requests)
    with ZipFile(io.BytesIO(data)) as archive:
        if road_artifact:
            assert document.road_artifact_sha256 == road_artifact['content_sha256']
            xml = archive.read('word/document.xml').decode()
            assert '留存道路路径' in xml and '0.69 公里' in xml
        images = [name for name in archive.namelist() if name.startswith("word/media/") and name.endswith(".png")]
        assert len(images) == 1
        image = archive.read(images[0])
    pixels = Image.open(io.BytesIO(image)).convert("RGB")
    assert pixels.width == 960 and pixels.height >= 700
    assert len(pixels.getcolors(pixels.width * pixels.height)) > 1000
    (tmp_path / "real-vector-result.docx").write_bytes(data)
    (tmp_path / "real-vector-map.png").write_bytes(image)
    if os.environ.get("AIC_TEST_PDF_OFFICE") == "1":
        from app.services.case_result_pdf import export_case_result_pdf

        pdf_document, pdf = export_case_result_pdf(db_session, saved["id"], road_artifact_id=artifact_id)
        assert pdf_document.content_sha256 == document.content_sha256
        assert pdf.startswith(b"%PDF-") and b"%%EOF" in pdf[-1024:]
        (tmp_path / "real-vector-result.pdf").write_bytes(pdf)
    (tmp_path / "resource-counts.json").write_text(json.dumps({
        "tiles": sum("/tiles/" in url for url in requests),
        "glyphs": sum("/glyphs/" in url for url in requests),
        "manifest_sha256": installed["package_hash"],
        "synthetic_case": True,
        "automatic_road_services": road_mode,
        "road_artifact_sha256": road_artifact['content_sha256'] if road_artifact else None,
        "upstream_profile_fixture": True, "redis_queue_tested": False,
    }))
    if os.environ.get('AIC_RENDER_EVIDENCE_DIR'):
        destination = Path(os.environ['AIC_RENDER_EVIDENCE_DIR'])
        destination.mkdir(parents=True, exist_ok=True)
        for name in ('real-vector-result.docx', 'real-vector-result.pdf', 'real-vector-map.png', 'resource-counts.json'):
            if (tmp_path / name).is_file():
                shutil.copyfile(tmp_path / name, destination / name)
