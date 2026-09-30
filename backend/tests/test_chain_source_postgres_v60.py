"""Opt-in test against this run's disposable, loopback-only PostgreSQL container."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def test_chain_migration_on_disposable_postgres_and_separate_restore():
    value = os.environ.get("AIC_V60_DISPOSABLE_PG_URL")
    container = os.environ.get("AIC_V60_DISPOSABLE_PG_CONTAINER", "")
    if not value:
        pytest.skip("new disposable PostgreSQL container not requested")
    url = make_url(value)
    assert url.host == "127.0.0.1" and url.database == "aic_v60_migration"
    assert url.username == "aic_v60_synthetic"
    assert container.startswith("aic-v60-migration-")
    assert os.environ.get("AIC_V60_DISPOSABLE_PG_CONFIRMED") == "1"
    backend = Path(__file__).resolve().parents[1]
    restored_url = url.set(database="aic_v60_restore")

    def migrate(target, direction, revision):
        return subprocess.run([sys.executable, "-m", "alembic", direction, revision],
            cwd=backend, capture_output=True, text=True, timeout=60,
            env={**os.environ, "DATABASE_URL": target.render_as_string(hide_password=False),
                 "SECRET_KEY": "synthetic-v60-migration-only", "ENABLE_VECTOR_DB": "false",
                 "AGENT_USE_EXTERNAL_MODEL": "false"})

    engine = create_engine(url)
    restored_engine = None
    try:
        with engine.connect() as db:
            assert db.scalar(text("SELECT to_regclass('public.cases')")) is None
        initial = migrate(url, "upgrade", "f94a53da8bc4")
        assert initial.returncode == 0, initial.stderr
        with engine.begin() as db:
            db.execute(text("INSERT INTO cases(id,case_number,occurred_time,description) VALUES "
                "(1,'PG-SYNTHETIC-A',now(),'升级前合成事实甲'),(2,'PG-SYNTHETIC-B',now(),'升级前合成事实乙')"))
            db.execute(text("INSERT INTO chain_links(id,case_id_a,case_id_b,link_type,status,confidence,distance_km,time_diff_days,confirmed_by) "
                "VALUES (1,1,2,'upstream_transport','confirmed',0.5,2,1,'历史合成复核人')"))
        backup = subprocess.run(["docker", "exec", container, "pg_dump", "-U", url.username,
            "-d", url.database, "--no-owner", "--no-privileges"], capture_output=True, timeout=60)
        assert backup.returncode == 0, backup.stderr.decode()
        upgrade = migrate(url, "upgrade", "v60c01")
        assert upgrade.returncode == 0, upgrade.stderr
        with engine.begin() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "v60c01"
            assert tuple(db.execute(text("SELECT status,confirmed_by,source_hash_a,source_hash_b FROM chain_links")).one()) == (
                "confirmed", "历史合成复核人", None, None)
            db.execute(text("UPDATE cases SET description='升级后新增事实' WHERE id=1"))
            db.execute(text("INSERT INTO case_tips(case_id,content,verification_status) VALUES (1,'升级后未核实线索','pending')"))
        refused = migrate(url, "downgrade", "f94a53da8bc4")
        assert refused.returncode != 0
        assert "restore_compatible_backup_required_for_chain_version_downgrade" in refused.stderr
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as db:
            db.execute(text("CREATE DATABASE aic_v60_restore"))
        restore = subprocess.run(["docker", "exec", "-i", container, "psql", "-U", url.username,
            "-d", restored_url.database, "-v", "ON_ERROR_STOP=1"], input=backup.stdout,
            capture_output=True, timeout=60)
        assert restore.returncode == 0, restore.stderr.decode()
        restored_engine = create_engine(restored_url)
        with restored_engine.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "f94a53da8bc4"
            assert db.scalar(text("SELECT description FROM cases WHERE id=1")) == "升级前合成事实甲"
        reupgraded = migrate(restored_url, "upgrade", "v60c01")
        assert reupgraded.returncode == 0, reupgraded.stderr
        with restored_engine.connect() as db:
            assert tuple(db.execute(text("SELECT status,confirmed_by FROM chain_links")).one()) == (
                "confirmed", "历史合成复核人")
        with engine.connect() as db:
            assert db.scalar(text("SELECT description FROM cases WHERE id=1")) == "升级后新增事实"
            assert db.scalar(text("SELECT content FROM case_tips")) == "升级后未核实线索"
    finally:
        engine.dispose()
        if restored_engine is not None:
            restored_engine.dispose()
