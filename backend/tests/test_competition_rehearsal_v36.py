from datetime import datetime, timezone
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.config import settings
from app.database import Base
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot, MapSnapshotFeature, OperationalArea, PublicMapBundle
from app.release_checks.competition_v36 import run_rehearsal_rounds


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def demo_scope(monkeypatch) -> tuple[Session, OperationalArea, MapSnapshot]:
    monkeypatch.setattr(settings, "ENABLE_VECTOR_DB", False)
    monkeypatch.setattr(settings, "AGENT_USE_EXTERNAL_MODEL", False)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = local()
    area = OperationalArea(
        code="competition-demo",
        name="竞赛脱敏演示区",
        is_default=True,
        status="active",
    )
    bundle = PublicMapBundle(
        bundle_id="competition-demo-map",
        provider="fixture",
        source_version="2026-09-09",
        license_record="test-only",
        bounds=[124.0, 45.0, 126.0, 47.0],
        manifest={"fixture": True},
        package_hash="a" * 64,
        status="accepted",
    )
    db.add_all([area, bundle])
    db.flush()
    snapshot = MapSnapshot(
        id="competition-snapshot",
        version="competition-v1",
        operational_area_id=area.id,
        public_bundle_id=bundle.id,
        status="current",
        manifest={"fixture": True},
        feature_watermark="fixture",
        published_at=datetime.now(timezone.utc),
    )
    db.add(snapshot)
    db.flush()
    features = [
        ("脱敏生产目标A", "well", 46.001, 125.001, {"oil_type": "原油", "production_output": 90}),
        ("脱敏临时存储区B", "storage", 46.006, 125.006, {}),
        ("脱敏生产便道C", "road", 46.003, 125.003, {}),
    ]
    for index, (name, asset_type, latitude, longitude, attributes) in enumerate(features, start=1):
        asset = JurisdictionAsset(
            operational_area_id=area.id,
            canonical_key=f"competition:{index}",
            name=name,
            asset_type=asset_type,
            geometry_type="point",
            latitude=latitude,
            longitude=longitude,
            source="synthetic_demo",
            status="active",
            verified=True,
            verification_state="source_verified",
            coordinate_system="EPSG:4326",
            attributes=attributes,
        )
        db.add(asset)
        db.flush()
        db.add(
            MapSnapshotFeature(
                snapshot_id=snapshot.id,
                operational_area_id=area.id,
                asset_id=asset.id,
                name=name,
                asset_type=asset_type,
                geometry_type="point",
                latitude=latitude,
                longitude=longitude,
                source="synthetic_demo",
                status="active",
                verified=True,
                verification_state="source_verified",
                attributes=attributes,
            )
        )
    db.commit()
    try:
        yield db, area, snapshot
    finally:
        db.close()
        engine.dispose()


def test_five_round_competition_rehearsal_uses_automatic_v36_flow(demo_scope):
    db, area, snapshot = demo_scope

    result = run_rehearsal_rounds(
        db,
        operational_area_id=area.id,
        map_snapshot_id=snapshot.id,
        run_count=5,
    )

    assert result["status"] == "passed"
    assert result["successful_runs"] == 5
    assert [item["fault_scenario"] for item in result["runs"]] == [
        "none",
        "external_model_unavailable",
        "outbox_worker_suspended_then_recovered",
        "worker_restart_after_claim",
        "idempotent_replay",
    ]
    for item in result["runs"]:
        assert item["case_saved_before_background_processing"] is True
        assert item["profile_status"] == "completed"
        assert item["candidate_count"] in {1, 2, 3}
        assert item["evidence_coverage"] == 1.0
        assert item["counter_evidence_or_gap_coverage"] == 1.0
        assert item["recommendation_count"] in {1, 2, 3}
        assert item["formal_case_changed"] is False
        assert item["formal_domain_changed"] is False
        assert item["execution_task_created"] is False
        assert item["duration_seconds"] < 360
    assert result["runs"][2]["fault_observation"]["recovery_poll"] == {
        "selected": 1,
        "completed": 1,
        "failed": 0,
    }
    assert result["runs"][1]["external_model_calls"] == 1
    assert result["runs"][1]["fault_observation"] == {
        "agent_run_status": "degraded",
        "external_model_attempts": 1,
        "usage_error_code": "TimeoutError",
        "fallback_mode": "deterministic_fallback",
    }
    assert result["runs"][2]["fault_observation"]["pending_before_recovery"] is True
    assert result["runs"][2]["fault_observation"]["independent_worker_session"] is True
    assert result["runs"][3]["profile_event_attempts"] == 2
    assert result["runs"][3]["fault_observation"]["expired_claim_recovered"] is True
    assert result["runs"][3]["fault_observation"]["stale_finish_rejected"] is True


def _write_real_bundle(path: Path) -> Path:
    mbtiles_path = path / "competition.mbtiles"
    connection = sqlite3.connect(mbtiles_path)
    connection.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    connection.execute(
        "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, "
        "tile_row INTEGER, tile_data BLOB)"
    )
    connection.execute("INSERT INTO metadata VALUES ('format', 'png')")
    connection.execute("INSERT INTO metadata VALUES ('bounds', '124,45,126,47')")
    connection.execute("INSERT INTO metadata VALUES ('minzoom', '0')")
    connection.execute("INSERT INTO metadata VALUES ('maxzoom', '0')")
    connection.execute("INSERT INTO metadata VALUES ('minzoom', '0')")
    connection.execute("INSERT INTO metadata VALUES ('maxzoom', '0')")
    connection.execute(
        "INSERT INTO tiles VALUES (0, 0, 0, ?)",
        (
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ),
        ),
    )
    connection.commit()
    connection.close()
    mbtiles = mbtiles_path.read_bytes()
    manifest = {
        "schema_version": "1.0",
        "bundle_id": "competition-real-bundle",
        "provider": "synthetic-public-map",
        "source_version": "test-v1",
        "license": "test-only",
        "attribution": "测试公共地图",
        "bounds": [124.0, 45.0, 126.0, 47.0],
        "min_zoom": 0,
        "max_zoom": 0,
        "tile_count": 1,
        "contains_internal_data": False,
        "files": [
            {
                "name": "basemap.mbtiles",
                "sha256": hashlib.sha256(mbtiles).hexdigest(),
                "size": len(mbtiles),
            }
        ],
    }
    bundle_path = path / "competition-map.zip"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("basemap.mbtiles", mbtiles)
    return bundle_path


def test_competition_rehearsal_cli_executes_real_bundle_and_writes_evidence(tmp_path):
    bundle_path = _write_real_bundle(tmp_path)
    evidence_path = tmp_path / "competition-evidence.json"
    cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.release_checks.competition_v36",
            "--bundle",
            str(bundle_path),
            "--evidence",
            str(evidence_path),
            "--runs",
            "5",
        ],
        cwd=REPOSITORY_ROOT / "backend",
        check=False,
        capture_output=True,
        text=True,
    )
    assert cli.returncode == 0
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "passed"
    assert evidence["successful_runs"] == 5
    assert evidence["map_package"]["tile_count"] == 1
    assert len(evidence["candidate_source_sha256"]) == 64
    assert evidence["candidate_source_file_count"] > 100
    assert evidence["candidate_source_stable_during_rehearsal"] is True
    assert evidence["runs"][1]["fault_observation"]["usage_error_code"] == "TimeoutError"
    assert evidence["runs"][3]["fault_observation"]["stale_finish_rejected"] is True
    assert evidence_path.stat().st_mode & 0o777 == 0o600

    original_evidence = evidence_path.read_bytes()
    replay = subprocess.run(
        cli.args,
        cwd=REPOSITORY_ROOT / "backend",
        check=False,
        capture_output=True,
        text=True,
    )
    assert replay.returncode != 0
    assert evidence_path.read_bytes() == original_evidence

    script = (REPOSITORY_ROOT / "scripts/verify-v36-competition-demo.sh").read_text(
        encoding="utf-8"
    )
    assert "MAP_BUNDLE_FILE" in script
    assert "app.release_checks.competition_v36" in script
    assert "--runs 5" in script
    assert script.index('case "$MAP_BUNDLE_FILE"') < script.index('[ -r "$MAP_BUNDLE_FILE" ]')
