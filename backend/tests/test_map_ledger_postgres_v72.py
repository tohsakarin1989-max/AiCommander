"""Opt-in real migration/concurrent ledger receipt/original-byte restore probe."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session


@pytest.mark.skipif(os.environ.get("AIC_V72_DISPOSABLE_PG") != "1",
                    reason="requires explicit disposable PostgreSQL v7.2 validation")
def test_ledger_upgrade_parallel_ingest_correction_and_original_restore():
    password = os.environ.get("AIC_V70_SYNTHETIC_PASSWORD")
    assert password, "only the disposable container password may be supplied"
    container, username = "aic-v70-validation-pg", "aic_v70_synthetic"
    inspected = subprocess.run(["docker", "inspect", "--format", "{{json .HostConfig.PortBindings}}", container],
                               capture_output=True, check=True, timeout=20)
    assert json.loads(inspected.stdout).get("5432/tcp") == [{"HostIp": "127.0.0.1", "HostPort": "15470"}]
    names = [f"aic_v72_{kind}_{uuid4().hex[:10]}" for kind in ("upgrade", "restore")]
    url = URL.create("postgresql+psycopg2", username=username, password=password,
                     host="127.0.0.1", port=15470, database="postgres")
    admin = create_engine(url)
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for name in names:
            assert connection.scalar(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}) is None
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    print("Synthetic v7.2 databases retained:", ", ".join(names))
    engine, restored = create_engine(url.set(database=names[0])), create_engine(url.set(database=names[1]))

    from alembic import command
    from alembic.config import Config
    from app.models.case import Case
    from app.models.case_source import EvidenceObject
    from app.models.jurisdiction import JurisdictionAsset
    from app.models.map_foundation import MapFeatureClaim, MapFieldDecision, MapIngestRun, JurisdictionAssetVersion
    from app.services.map_foundation_service import MapFoundationService as Service
    from app.services.map_ingest_execution import retry_rows
    from app.services.map_ingest_originals import read_original
    from tests.test_map_ledger_v72 import BASE, PRODUCTION, MAPPING, csv_bytes

    def migrate(target):
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, target)

    def session(target=engine):
        db = Session(target)
        db.info.update(principal_user_id=72, authorized_area_ids=(1,), area_access_levels={1: "manage"})
        return db

    try:
        migrate("v71d01")
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO cases(case_number,description,operational_area_id) "
                "VALUES ('SYN-V72-BEFORE','升级前合成原始记录',1)"))
            connection.execute(text("INSERT INTO users(id,username,display_name,password_hash,role) "
                "VALUES (72,'v72-pg-synthetic','合成管理员','not-a-real-login','admin')"))
        migrate("v72m01")
        with session() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "v72m01"
            assert db.query(Case).one().description == "升级前合成原始记录"
            source = Service.create_source(db, {"source_key": "v72-synthetic-ledger", "name": "合成台账", "source_type": "ledger", "operational_area_id": 1})
            template = Service.create_template(db, {"source_id": source.id, "name": "合成模板", "coordinate_system": "wgs84",
                "field_mapping": {"external_id": "井号", "name": "井名", "asset_type": "类型", "longitude": "经度", "latitude": "纬度", **MAPPING}})
            source_id, template_id = source.id, template.id
        content = csv_bytes([{**BASE, **PRODUCTION}])
        barrier = Barrier(3)
        def ingest(_):
            with session() as db:
                barrier.wait(timeout=20)
                run, replay = Service.ingest(db, source_id=source_id, template_id=template_id,
                    filename="合成台账.csv", content=content, source_revision="1", created_by=72)
                return run.id, replay
        with ThreadPoolExecutor(max_workers=3) as pool:
            receipts = list(pool.map(ingest, range(3)))
        assert len({identifier for identifier, _ in receipts}) == 1
        assert sorted(replay for _, replay in receipts) == [False, True, True]
        run_id = receipts[0][0]
        with session() as db:
            assert db.query(JurisdictionAsset).count() == db.query(JurisdictionAssetVersion).count() == 1
            assert db.query(MapIngestRun).count() == db.query(EvidenceObject).count() == 1
            assert read_original(db, run_id)[0] == content
            same, _ = Service.ingest(db, source_id=source_id, template_id=template_id,
                filename="合成台账.csv", content=content, source_revision="2", created_by=72)
            assert same.updated_assets == 0 and db.query(JurisdictionAssetVersion).count() == 1
            bad_content = csv_bytes([{**BASE, **PRODUCTION, "井号": "B", "经度": "待核"}])
            bad, _ = Service.ingest(db, source_id=source_id, template_id=template_id,
                filename="异常合成台账.csv", content=bad_content, source_revision="bad-1", created_by=72)
            claim = db.query(MapFeatureClaim).filter_by(run_id=bad.id).one()
            request = {"request_id": "synthetic-retry-72", "note": "合成纠错",
                       "rows": [{"claim_id": claim.id, "values": {**BASE, **PRODUCTION, "井号": "B"}}]}
            plan = retry_rows(db, bad.id, request, preview=True)
            correction, _ = retry_rows(db, bad.id, {**request, "plan_token": plan["plan_token"]}, created_by=72)
            correction_id = correction.id
            assert read_original(db, correction_id)[0] == bad_content
            assert db.query(JurisdictionAsset).count() == 2
            expected = {model.__tablename__: db.query(model).count()
                        for model in (Case, JurisdictionAsset, JurisdictionAssetVersion, MapIngestRun, MapFeatureClaim, MapFieldDecision, EvidenceObject)}
        backup = subprocess.run(["docker", "exec", container, "pg_dump", "-U", username, "-d", names[0],
            "--no-owner", "--no-privileges"], capture_output=True, check=True, timeout=60)
        subprocess.run(["docker", "exec", "-i", container, "psql", "-U", username, "-d", names[1], "-v", "ON_ERROR_STOP=1"],
                       input=backup.stdout, capture_output=True, check=True, timeout=60)
        with session(restored) as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "v72m01"
            for model in (Case, JurisdictionAsset, JurisdictionAssetVersion, MapIngestRun, MapFeatureClaim, MapFieldDecision, EvidenceObject):
                assert db.query(model).count() == expected[model.__tablename__]
            assert read_original(db, run_id)[0] == content
            assert read_original(db, correction_id)[0] == bad_content
            again, replay = Service.ingest(db, source_id=source_id, template_id=template_id,
                filename="合成台账.csv", content=content, source_revision="1", created_by=72)
            assert replay and again.id == run_id and db.query(JurisdictionAsset).count() == 2
            assert db.query(Case).one().description == "升级前合成原始记录"
    finally:
        engine.dispose()
        restored.dispose()
