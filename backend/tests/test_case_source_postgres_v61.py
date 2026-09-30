"""Opt-in real PostgreSQL migration, restore and empty-target initialization."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def test_v61_disposable_postgres_migration_restore_and_fresh_initialization():
    value = os.environ.get("AIC_V61_DISPOSABLE_PG_URL")
    if not value:
        pytest.skip("disposable PostgreSQL explicitly not requested")
    container = os.environ["AIC_V61_DISPOSABLE_PG_CONTAINER"]
    url = make_url(value)
    assert url.host == "127.0.0.1" and url.database == "aic_v61_migration"
    assert url.username == "aic_v61_synthetic" and container.startswith("aic-v61-source-")
    assert os.environ.get("AIC_V61_DISPOSABLE_PG_CONFIRMED") == "1"
    backend = Path(__file__).resolve().parents[1]
    engines = []

    def migrate(target, direction, revision):
        return subprocess.run([sys.executable, "-m", "alembic", direction, revision], cwd=backend,
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "DATABASE_URL": target.render_as_string(hide_password=False),
                 "SECRET_KEY": "synthetic-source-migration", "AGENT_MODE": "off",
                 "ENABLE_VECTOR_DB": "false", "AGENT_USE_EXTERNAL_MODEL": "false"})

    try:
        engine = create_engine(url)
        engines.append(engine)
        with engine.connect() as db:
            assert db.scalar(text("SELECT to_regclass('public.cases')")) is None
        initial = migrate(url, "upgrade", "v60c01")
        assert initial.returncode == 0, initial.stderr
        with engine.begin() as db:
            db.execute(text("INSERT INTO cases(id,case_number,occurred_time,description,oil_volume) VALUES "
                "(1,'PG61-A',now(),'原始合成案件甲',120),(2,'PG61-B',now(),'原始合成案件乙',0)"))
            db.execute(text("INSERT INTO chain_links(id,case_id_a,case_id_b,link_type,status,confidence,distance_km,time_diff_days,confirmed_by) "
                "VALUES (1,1,2,'upstream_transport','confirmed',0.5,2,1,'合成历史复核人')"))
        upgraded = migrate(url, "upgrade", "v61s01")
        assert upgraded.returncode == 0, upgraded.stderr
        with engine.begin() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "v61s01"
            assert db.scalar(text("SELECT count(*) FROM case_revisions")) == 0
            assert tuple(db.execute(text("SELECT oil_volume,oil_volume_unit,time_precision FROM cases WHERE id=1")).one()) == (120, "unknown", None)
            db.execute(text("INSERT INTO cases(id,case_number,description,time_precision,time_expression) VALUES "
                            "(3,'PG61-UNKNOWN','升级后原始记录','unknown','昨晚')"))
            db.execute(text("INSERT INTO case_revisions(case_id,revision,source_hash,payload) VALUES "
                            "(3,1,:hash,:payload)"), {"hash": "a" * 64, "payload": '{"original":"升级后原始记录"}'})
            db.execute(text("INSERT INTO evidence_objects(storage_key,sha256,media_type,sensitivity,availability,content) "
                            "VALUES('synthetic-object',:hash,'text/plain','internal','available',:content)"),
                       {"hash": "b" * 64, "content": b"synthetic evidence bytes"})
            db.execute(text("SELECT setval(pg_get_serial_sequence('cases','id'),3)"))
        # Authorised whole-case removal must not be blocked by the new source
        # graph; no separate revision-deletion operation is exposed.
        from sqlalchemy.orm import Session
        from app.models.case import CaseEvidence
        from app.models.case_source import SourceReference
        from app.services.case_service import CaseService
        from app.services.case_source_service import CaseSourceService
        with Session(engine) as session:
            session.info["authorized_area_ids"] = None
            removable = CaseService.create_case(session, "PG61-DELETE", time_expression="不详")
            source = CaseSourceService.latest_revision(session, removable.id)
            reference = SourceReference(case_id=removable.id, source_revision_id=source.id,
                                        kind="text", locator={"quote": "合成原文"})
            session.add(reference)
            session.flush()
            session.add(CaseEvidence(case_id=removable.id, source_reference_id=reference.id, title="原文出处"))
            session.commit()
            assert CaseService.delete_case(session, removable.id) is True
        with engine.begin() as db:
            first_revision = db.scalar(text("SELECT id FROM case_revisions WHERE case_id=3 AND revision=1"))
            next_revision = db.scalar(text("INSERT INTO case_revisions(case_id,revision,source_hash,payload) "
                "VALUES(3,2,:hash,:payload) RETURNING id"), {"hash": "a" * 64, "payload": '{"original":"升级后原始记录"}'})
            for sequence, source_id in ((1, first_revision), (2, next_revision)):
                db.execute(text("INSERT INTO case_analysis_profiles(id,case_id,profile_version,source_hash,schema_version,"
                    "dictionary_version,payload,quality_score,analysis_readiness,is_current,source_revision_id) "
                    "VALUES(:id,3,:version,:hash,'6.1.0','synthetic','{}',NULL,'partial',:current,:source)"),
                    {"id": f"synthetic-profile-{sequence}", "version": sequence, "hash": "a" * 64,
                     "current": sequence == 2, "source": source_id})
            assert db.scalar(text("SELECT count(*) FROM case_analysis_profiles WHERE case_id=3")) == 2
        refused = migrate(url, "downgrade", "v60c01")
        assert refused.returncode != 0 and "restore_compatible_backup_required" in refused.stderr
        backup = subprocess.run(["docker", "exec", container, "pg_dump", "-U", url.username,
                                 "-d", url.database, "--no-owner", "--no-privileges"], capture_output=True, timeout=60)
        assert backup.returncode == 0, backup.stderr.decode()
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as db:
            db.execute(text("CREATE DATABASE aic_v61_restore"))
            db.execute(text("CREATE DATABASE aic_v61_fresh"))
            db.execute(text("CREATE DATABASE aic_v61_other_schema_table"))
            db.execute(text("CREATE DATABASE aic_v61_other_schema_materialized"))
        restored_url = url.set(database="aic_v61_restore")
        restore = subprocess.run(["docker", "exec", "-i", container, "psql", "-U", url.username,
                                  "-d", restored_url.database, "-v", "ON_ERROR_STOP=1"],
                                 input=backup.stdout, capture_output=True, timeout=60)
        assert restore.returncode == 0, restore.stderr.decode()
        restored_engine = create_engine(restored_url)
        engines.append(restored_engine)
        with restored_engine.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "v61s01"
            assert tuple(db.execute(text("SELECT status,confirmed_by FROM chain_links")).one()) == ("confirmed", "合成历史复核人")
            assert db.scalar(text("SELECT payload FROM case_revisions WHERE case_id=3"))["original"] == "升级后原始记录"
            assert bytes(db.scalar(text("SELECT content FROM evidence_objects"))) == b"synthetic evidence bytes"
            assert db.scalar(text("SELECT occurred_time FROM cases WHERE id=3")) is None
        from init_fresh_db import initialize_empty_database
        fresh = url.set(database="aic_v61_fresh").render_as_string(hide_password=False)
        # Fresh initialization always uses the current head; historical upgrade
        # and restore above deliberately remain pinned to the v6.1 contract.
        assert initialize_empty_database(fresh, confirmed=True) == "v62f01"
        with pytest.raises(ValueError, match="target_not_empty"):
            initialize_empty_database(fresh, confirmed=True)
        # Empty public schema does not mean an empty target: protect both
        # non-public ordinary tables and standalone materialized views.
        for database, create_object in (
            ("aic_v61_other_schema_table", "CREATE TABLE private_source.original AS SELECT 'synthetic-original'::text AS marker"),
            ("aic_v61_other_schema_materialized", "CREATE MATERIALIZED VIEW private_source.original AS SELECT 'synthetic-original'::text AS marker"),
        ):
            guarded_url = url.set(database=database)
            guarded_engine = create_engine(guarded_url)
            engines.append(guarded_engine)
            with guarded_engine.begin() as db:
                db.execute(text("CREATE SCHEMA private_source"))
                db.execute(text(create_object))
            with pytest.raises(ValueError, match="target_not_empty_no_changes_performed"):
                initialize_empty_database(guarded_url.render_as_string(hide_password=False), confirmed=True)
            with guarded_engine.connect() as db:
                assert db.scalar(text("SELECT marker FROM private_source.original")) == "synthetic-original"
                assert db.scalar(text("SELECT to_regclass('public.alembic_version')")) is None
                assert db.scalar(text("SELECT to_regclass('public.cases')")) is None
        with engine.connect() as db:
            assert db.scalar(text("SELECT description FROM cases WHERE id=3")) == "升级后原始记录"
    finally:
        for engine in engines:
            engine.dispose()
