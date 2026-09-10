"""在独立数据库升级，回退使用兼容备份而非丢弃历史成果。"""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_case_result_migration_and_backup_preserve_source_data(tmp_path):
    database = tmp_path / "upgraded.sqlite"
    backup = tmp_path / "v40.sqlite"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database}", "ENABLE_VECTOR_DB": "false"}
    backend = Path(__file__).resolve().parents[1]

    def migrate(direction, revision):
        return subprocess.run([sys.executable, "-m", "alembic", direction, revision], cwd=backend,
                              env=environment, capture_output=True, text=True, timeout=60)

    initial = migrate("upgrade", "f830b2152595")
    assert initial.returncode == 0, initial.stderr
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("INSERT INTO cases(case_number,occurred_time,description) VALUES ('SYNTHETIC-MIGRATION','2026-09-11','升级前原文')")
    with closing(sqlite3.connect(database)) as db, closing(sqlite3.connect(backup)) as target:
        db.backup(target)
    upgraded = migrate("upgrade", "09ac731646a1")
    assert upgraded.returncode == 0, upgraded.stderr
    with closing(sqlite3.connect(database)) as db, db:
        assert db.execute("SELECT description FROM cases").fetchone()[0] == "升级前原文"
        columns = {row[1] for row in db.execute("PRAGMA table_info(case_result_snapshots)")}
        assert {"case_id", "case_profile_id", "content", "content_sha256", "created_at"} <= columns
        db.execute("UPDATE cases SET description='升级后新增原文'")
        before = list(db.iterdump())
    refused = migrate("downgrade", "f830b2152595")
    assert refused.returncode != 0
    assert "restore_compatible_backup_required_for_case_results_downgrade" in refused.stderr
    with closing(sqlite3.connect(database)) as db:
        assert list(db.iterdump()) == before
    restored = tmp_path / "restored.sqlite"
    with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(restored)) as target:
        source.backup(target)
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT description FROM cases").fetchone()[0] == "升级前原文"
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "f830b2152595"
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT description FROM cases").fetchone()[0] == "升级后新增原文"
