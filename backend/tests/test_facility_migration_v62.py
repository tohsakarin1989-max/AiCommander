"""Synthetic SQLite / explicitly disposable PostgreSQL v6.2 migration checks."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def migrate(url, revision, direction="upgrade"):
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-m", "alembic", direction, revision], cwd=backend,
        capture_output=True, text=True, timeout=60, env={**os.environ,
        "DATABASE_URL": str(url), "SECRET_KEY": "synthetic-v62-only", "ENABLE_VECTOR_DB": "false",
        "ENABLE_AGENT_LAB": "false", "AGENT_MODE": "off", "AGENT_USE_EXTERNAL_MODEL": "false"})
    assert result.returncode == 0, result.stderr


def exercise_upgrade(url):
    migrate(url, "v61s01")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO cases(id,case_number,description,oil_volume,oil_volume_unit) "
                        "VALUES(1,'SYN62-CASE','合成原始案情',120,'unknown')"))
        db.execute(text("INSERT INTO users(id,username,display_name,password_hash,role) "
                        "VALUES(1,'synthetic-v62','合成用户','not-a-real-password','admin')"))
        db.execute(text("INSERT INTO jurisdiction_assets(id,operational_area_id,name,asset_type,source,valid_from) "
                        "VALUES(1,1,'合成旧设施','well','manual','2025-01-01T00:00:00+00:00')"))
        db.execute(text("INSERT INTO jurisdiction_asset_versions(id,asset_id,version,snapshot,change_type) "
                        "VALUES(1,1,1,:snapshot,'manual_created')"),
                   {"snapshot": '{"name":"合成旧设施","valid_from":"2025-01-01T00:00:00Z"}'})
        if engine.dialect.name == "postgresql":
            for table in ("jurisdiction_assets", "jurisdiction_asset_versions", "cases", "users"):
                db.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}','id'),1)"))
    migrate(url, "v62f01")
    with engine.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "v62f01"
        assert tuple(db.execute(text("SELECT temporal_status,valid_from,valid_to,known_at FROM jurisdiction_asset_versions WHERE id=1")).one()) == ("observed_only", None, None, None)
        assert db.scalar(text("SELECT count(*) FROM facility_source_identities")) == 0
        assert db.scalar(text("SELECT count(*) FROM facility_identity_decisions")) == 0
        assert tuple(db.execute(text("SELECT description,oil_volume,oil_volume_unit FROM cases WHERE id=1")).one()) == ("合成原始案情", 120, "unknown")
        assert "case_facility_associations" in inspect(db).get_table_names()
    # Exercise new FKs and immutable-history contract through the actual services.
    from app.models.case import Case
    from app.models.case_source import SourceReference
    from app.models.case_facility_association import CaseFacilityAssociation
    from app.models.map_foundation import FacilitySourceIdentity
    from app.services.case_source_service import CaseSourceService
    from app.services.facility_identity_service import FacilityIdentityService
    from app.services.map_foundation_service import MapFoundationService
    with Session(engine) as db:
        db.info["authorized_area_ids"] = None
        source = MapFoundationService.create_source(db, {"source_key": "synthetic-v62", "name": "合成来源",
            "source_type": "ledger", "operational_area_id": 1})
        template = MapFoundationService.create_template(db, {"source_id": source.id, "name": "合成模板", "coordinate_system": "wgs84",
            "field_mapping": {"external_id": "id", "name": "name", "asset_type": "type", "longitude": "lon", "latitude": "lat", "valid_from": "from"}})
        MapFoundationService.ingest(db, source_id=source.id, template_id=template.id, filename="synthetic.csv",
            content=b"id,name,type,lon,lat,from\nSYN-WELL,Synthetic,well,125.1,46.6,2026-01-01T00:00:00Z\n",
            source_revision="synthetic-1", created_by=1)
        identity = db.query(FacilitySourceIdentity).one()
        locked_queries = []
        def record_locks(_connection, _cursor, statement, _parameters, _context, _executemany):
            if "FOR UPDATE" in statement:
                locked_queries.append(statement)
        if engine.dialect.name == "postgresql":
            event.listen(engine, "before_cursor_execute", record_locks)
        bound = FacilityIdentityService.bind(db, identity.id, 1, actor_id=1, note="合成映射", request_key="synthetic-bind")
        FacilityIdentityService.revoke(db, identity.id, actor_id=1, note="合成撤销", request_key="synthetic-revoke", previous_decision_id=bound["id"])
        if engine.dialect.name == "postgresql":
            event.remove(engine, "before_cursor_execute", record_locks)
            assert len(locked_queries) == 4
            assert "FROM operational_areas" in locked_queries[0]
            assert "FROM facility_source_identities" in locked_queries[1]
            assert "FROM operational_areas" in locked_queries[2]
            assert "FROM facility_source_identities" in locked_queries[3]
        revision, _ = CaseSourceService.capture_change(db, db.get(Case, 1))
        reference = SourceReference(case_id=1, source_revision_id=revision.id, kind="case_text", locator={"quote": "合成原始案情"})
        db.add(reference)
        db.flush()
        db.add(CaseFacilityAssociation(case_id=1, asset_id=1, source_reference_id=reference.id,
            source_revision_id=revision.id, relation_type="recorded", note="合成人工关系", request_key="synthetic-association", created_by=1))
        db.commit()
    if engine.dialect.name == "sqlite":
        with engine.connect() as db:
            assert db.execute(text("PRAGMA foreign_key_check")).all() == []
            assert db.scalar(text("PRAGMA integrity_check")) == "ok"
    migrate(url, "v62f01")
    engine.dispose()


def test_v62_sqlite_upgrade_preserves_raw_sources_without_guessing_validity(tmp_path):
    exercise_upgrade(f"sqlite:///{tmp_path / 'synthetic-v62.sqlite'}")


def test_v62_disposable_postgres_upgrade_and_independent_restore():
    value = os.environ.get("AIC_V62_DISPOSABLE_PG_URL")
    if not value:
        pytest.skip("disposable PostgreSQL explicitly not requested")
    url = make_url(value)
    container = os.environ["AIC_V62_DISPOSABLE_PG_CONTAINER"]
    assert url.host == "127.0.0.1" and url.database == "aic_v62_migration"
    assert url.username == "aic_v62_synthetic" and container.startswith("aic-v62-source-")
    assert os.environ.get("AIC_V62_DISPOSABLE_PG_CONFIRMED") == "1"
    exercise_upgrade(value)
    backup = subprocess.run(["docker", "exec", container, "pg_dump", "-U", url.username,
        "-d", url.database, "--no-owner", "--no-privileges"], capture_output=True, timeout=60)
    assert backup.returncode == 0, backup.stderr.decode()
    engine = create_engine(url)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as db:
            db.execute(text("CREATE DATABASE aic_v62_restore"))
        restored = subprocess.run(["docker", "exec", "-i", container, "psql", "-U", url.username,
            "-d", "aic_v62_restore", "-v", "ON_ERROR_STOP=1"], input=backup.stdout, capture_output=True, timeout=60)
        assert restored.returncode == 0, restored.stderr.decode()
        restored_engine = create_engine(url.set(database="aic_v62_restore"))
        try:
            with restored_engine.connect() as db:
                assert db.scalar(text("SELECT version_num FROM alembic_version")) == "v62f01"
                assert db.scalar(text("SELECT description FROM cases WHERE id=1")) == "合成原始案情"
                assert db.scalar(text("SELECT count(*) FROM facility_identity_decisions")) == 2
                assert db.scalar(text("SELECT note FROM case_facility_associations")) == "合成人工关系"
                assert tuple(db.execute(text("SELECT temporal_status,valid_from,known_at FROM jurisdiction_asset_versions WHERE id=1")).one()) == ("observed_only", None, None)
        finally:
            restored_engine.dispose()
    finally:
        engine.dispose()
