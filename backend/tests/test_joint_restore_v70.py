"""Opt-in real PostgreSQL + map files + original evidence recovery rehearsal.

Only the disposable container/name/port below are accepted. Existing databases
are never cleared; created databases and the synthetic backup are retained for
inspection. No live application, worker, business data, image build or network
download is involved.
"""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session


CONTAINER = "aic-v70-validation-pg"
PG_USER = "aic_v70_synthetic"
SOURCE_DB = "aic_v70_joint_source"
RESTORE_DB = "aic_v70_joint_restore"
ROOT = Path(__file__).resolve().parents[2]


def _docker(*args, stdin=None):
    result = subprocess.run(["docker", *args], input=stdin, capture_output=True,
                            check=False, timeout=90)
    if result.returncode:
        # Only the disposable CLI and synthetic migration diagnostic; no config
        # or credential values are included in these command arguments.
        raise AssertionError(result.stderr.decode(errors="replace")[-4000:])
    return result.stdout


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _inventory(root):
    result = {}
    for item in sorted(root.rglob("*")):
        assert not item.is_symlink()
        if item.is_file():
            value = item.read_bytes()
            result[item.relative_to(root).as_posix()] = {"bytes": len(value), "sha256": _hash(value)}
    assert result
    return result


@pytest.mark.skipif(os.environ.get("AIC_V70_JOINT_RESTORE") != "1",
                    reason="requires explicitly authorized disposable v7.0 PostgreSQL container")
def test_real_postgres_maps_and_originals_restore_together(tmp_path, monkeypatch):
    password = os.environ.get("AIC_V70_SYNTHETIC_PASSWORD")
    assert password, "synthetic container password must be passed via environment"
    evidence_dir = Path(os.environ.get("AIC_V70_JOINT_EVIDENCE_DIR", ""))
    assert evidence_dir.is_absolute() and not evidence_dir.exists(), "use a new explicit evidence directory"
    evidence_dir.mkdir(parents=True, mode=0o700)

    bindings = json.loads(_docker("inspect", "--format", "{{json .HostConfig.PortBindings}}", CONTAINER))
    assert bindings.get("5432/tcp") == [{"HostIp": "127.0.0.1", "HostPort": "15470"}]
    admin_url = URL.create("postgresql+psycopg2", username=PG_USER, password=password,
                           host="127.0.0.1", port=15470, database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        prior_databases = connection.execute(text("SELECT datname FROM pg_database ORDER BY datname")).scalars().all()
        assert SOURCE_DB not in prior_databases and RESTORE_DB not in prior_databases, "never overwrite a prior run"
        connection.execute(text(f'CREATE DATABASE "{SOURCE_DB}"'))
        connection.execute(text(f'CREATE DATABASE "{RESTORE_DB}"'))

    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from fastapi import UploadFile
    from app.api.case_sources import download_evidence, upload_evidence
    from app.config import settings
    from app.models.case import Case
    from app.models.case_source import CaseRevision, EvidenceObject, SourceReference
    from app.models.map_foundation import MapPackageArtifact, MapSnapshot
    from app.services.case_source_service import CaseSourceService
    from app.services.map_foundation_service import MapFoundationService
    from app.services.offline_map_service import OfflineMapService
    from tests.test_offline_maps import _bundle_bytes, VALID_PNG_TILE

    configuration = Config(str(ROOT / "backend/alembic.ini"))
    configuration.set_main_option("script_location", str(ROOT / "backend/alembic"))
    expected_head = ScriptDirectory.from_config(configuration).get_current_head()
    source_engine = create_engine(admin_url.set(database=SOURCE_DB))
    restored_engine = create_engine(admin_url.set(database=RESTORE_DB))
    source_maps = evidence_dir / "source-maps"
    restored_maps = evidence_dir / "restored-maps"
    source_maps.mkdir(mode=0o700)
    restored_maps.mkdir(mode=0o700)
    monkeypatch.setattr(settings, "MAP_PACKAGE_ROOT", str(source_maps))
    monkeypatch.setattr(settings, "ENABLE_AGENT_LAB", False)
    monkeypatch.setattr(settings, "AGENT_USE_EXTERNAL_MODEL", False)
    with source_engine.begin() as connection:
        configuration.attributes["connection"] = connection
        command.upgrade(configuration, "head")
    configuration.attributes.pop("connection")

    with Session(source_engine, autoflush=False) as db:
        area = MapFoundationService.ensure_default_area(db)
        area.boundary = {"type": "Polygon", "coordinates": [[
            [124.5, 46.2], [125.5, 46.2], [125.5, 46.8], [124.5, 46.8], [124.5, 46.2]]]}
        db.commit()
        area_id = area.id
        db.info.update(authorized_area_ids=(area_id,), default_operational_area_id=area_id,
                       area_access_levels={area_id: "manage"})
        case = Case(case_number="SYNTHETIC-V70-JOINT-001", operational_area_id=area_id,
                    occurred_time=datetime(2026, 9, 30, tzinfo=timezone.utc), time_precision="exact",
                    location="合成恢复核对位置", description="仅用于隔离联合恢复，没有真实案件信息。",
                    status="pending")
        db.add(case)
        db.flush()
        CaseSourceService.capture_change(db, case, change_type="created")
        db.commit()
        case_id = case.id
        original = upload_evidence(case_id, UploadFile(filename="synthetic-original.png",
                                   file=io.BytesIO(VALID_PNG_TILE)), db)
        original_digest = original["sha256"]
        reference_id = original["reference_id"]
        source_original = download_evidence(case_id, reference_id, db)
        assert source_original.body == VALID_PNG_TILE
        bundle, reused = OfflineMapService.import_bundle(db, filename="synthetic.zip",
            content=_bundle_bytes(tmp_path, bundle_id="synthetic-v70-joint-restore",
                                  attribution="合成一像素验收，不代表真实地理覆盖"), imported_by=None)
        assert reused is False
        snapshot, reused = OfflineMapService.build_snapshot(db, operational_area_id=area_id,
                                                            public_bundle_id=bundle.id, built_by=None)
        assert reused is False
        published = OfflineMapService.publish_snapshot(db, snapshot.id)
        snapshot_id, bundle_id = published.id, bundle.id
        source_manifest = OfflineMapService.resolved_manifest(db, published)
        assert OfflineMapService.read_tile(db, "current", 0, 0, 0, area_id=area_id)[0] == VALID_PNG_TILE
        source_revision = db.query(CaseRevision).filter_by(case_id=case_id).order_by(CaseRevision.revision.desc()).first()
        source_case_revision = (source_revision.id, source_revision.revision, source_revision.source_hash)
        checkpoint = datetime.now(timezone.utc).isoformat()

    # No writers or consumers are started for these databases. Closing the only
    # application Session establishes this synthetic rehearsal's stop-write point.
    source_engine.dispose()
    source_files = _inventory(source_maps)
    dump = _docker("exec", CONTAINER, "pg_dump", "-U", PG_USER, "-d", SOURCE_DB,
                   "--format=custom", "--no-owner", "--no-privileges")
    assert dump.startswith(b"PGDMP")
    dump_path = evidence_dir / "database.dump"
    dump_path.write_bytes(dump)
    dump_path.chmod(0o600)
    with tarfile.open(evidence_dir / "maps.tar", "w") as archive:
        for relative in source_files:
            archive.add(source_maps / relative, arcname=relative, recursive=False)
    (evidence_dir / "maps.tar").chmod(0o600)
    assert _inventory(source_maps) == source_files
    (evidence_dir / "map-inventory.json").write_text(json.dumps(source_files, ensure_ascii=False, indent=2))
    (evidence_dir / "database.dump.manifest").write_text(
        f"format=postgres-custom\napplication_version={(ROOT / 'VERSION').read_text().strip()}\n"
        f"database_revision={expected_head}\ncheckpoint_id={checkpoint}\n")

    _docker("exec", "-i", CONTAINER, "pg_restore", "-U", PG_USER, "-d", RESTORE_DB,
            "--exit-on-error", "--no-owner", "--no-privileges", stdin=dump)
    with tarfile.open(evidence_dir / "maps.tar", "r") as archive:
        assert all(member.isfile() and not Path(member.name).is_absolute()
                   and ".." not in Path(member.name).parts for member in archive.getmembers())
        archive.extractall(restored_maps, filter="data")
    assert _inventory(restored_maps) == source_files
    monkeypatch.setattr(settings, "MAP_PACKAGE_ROOT", str(restored_maps))
    with Session(restored_engine, autoflush=False) as db:
        db.info.update(authorized_area_ids=(area_id,), default_operational_area_id=area_id)
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == expected_head
        restored_case = db.query(Case).filter_by(id=case_id).one()
        assert restored_case.case_number == "SYNTHETIC-V70-JOINT-001"
        assert restored_case.description == "仅用于隔离联合恢复，没有真实案件信息。"
        revision = db.query(CaseRevision).filter_by(case_id=case_id).order_by(CaseRevision.revision.desc()).first()
        assert (revision.id, revision.revision, revision.source_hash) == source_case_revision
        evidence = db.get(EvidenceObject, original["evidence_object_id"])
        assert evidence.availability == "available"
        assert _hash(evidence.content) == original_digest
        assert db.query(SourceReference).filter_by(id=reference_id, case_id=case_id,
            evidence_object_id=evidence.id).one()
        assert download_evidence(case_id, reference_id, db).body == VALID_PNG_TILE
        current = OfflineMapService.current_snapshot(db, area_id)
        assert current.id == snapshot_id and current.public_bundle_id == bundle_id
        assert OfflineMapService.resolved_manifest(db, current) == source_manifest
        tile, content_type = OfflineMapService.read_tile(db, "current", 0, 0, 0, area_id=area_id)
        assert tile == VALID_PNG_TILE and content_type == "image/png"
        asset = db.query(MapPackageArtifact).filter_by(public_bundle_id=bundle_id, artifact_kind="mbtiles").one()
        assert _hash((restored_maps / asset.storage_key).read_bytes()) == asset.sha256
        assert OfflineMapService._snapshot_artifact_exists(db, current, verify_hash=True)

    # DB-only restoration must not be reported as map restoration. Exercise the
    # failure using another empty directory, never by damaging original files.
    empty_maps = evidence_dir / "empty-negative-control"
    empty_maps.mkdir(mode=0o700)
    monkeypatch.setattr(settings, "MAP_PACKAGE_ROOT", str(empty_maps))
    with Session(restored_engine) as db:
        with pytest.raises(ValueError, match="tile_store_unavailable"):
            OfflineMapService.read_tile(db, "current", 0, 0, 0, area_id=area_id)
    monkeypatch.setattr(settings, "MAP_PACKAGE_ROOT", str(source_maps))
    with Session(source_engine) as db:
        assert db.query(Case).count() == 1
        assert db.query(MapSnapshot).filter_by(status="current").one().id == snapshot_id
        assert download_evidence(case_id, reference_id, db).body == VALID_PNG_TILE
    assert _inventory(source_maps) == source_files
    with admin.connect() as connection:
        after_databases = connection.execute(text("SELECT datname FROM pg_database ORDER BY datname")).scalars().all()
        assert set(after_databases) == set(prior_databases) | {SOURCE_DB, RESTORE_DB}

    report = {"status": "passed", "checkpoint": checkpoint, "database_revision": expected_head,
              "application_version": (ROOT / "VERSION").read_text().strip(),
              "source_database": SOURCE_DB, "restore_database": RESTORE_DB,
              "snapshot_id": snapshot_id, "source_case_revision": source_case_revision,
              "database_dump_sha256": _hash(dump), "map_archive_sha256": _hash((evidence_dir / "maps.tar").read_bytes()),
              "map_files": len(source_files), "map_bytes": sum(item["bytes"] for item in source_files.values()),
              "original_sha256": original_digest, "restored_original_download": True,
              "restored_current_map_binding": True, "restored_tile_read": True,
              "database_only_map_read_rejected": True, "source_unchanged": True,
              "prior_databases_preserved": True, "new_databases_retained": True,
              "synthetic_one_pixel_only": True, "real_geographic_coverage_verified": False,
              "target_server_verified": False, "secrets_recovery_exercised": False}
    (evidence_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False), flush=True)
    source_engine.dispose()
    restored_engine.dispose()
    admin.dispose()
