"""Incremental migration and separate recovery never discard new case facts."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_chain_version_upgrade_and_separate_recovery_preserve_human_history(tmp_path):
    original = tmp_path / "v60.sqlite"
    backup = tmp_path / "v54-backup.sqlite"
    restored = tmp_path / "v54-restored.sqlite"
    backend = Path(__file__).resolve().parents[1]

    def migrate(database, direction, revision):
        return subprocess.run(
            [sys.executable, "-m", "alembic", direction, revision], cwd=backend,
            env={**os.environ, "DATABASE_URL": f"sqlite:///{database}", "ENABLE_VECTOR_DB": "false"},
            capture_output=True, text=True, timeout=60,
        )

    initial = migrate(original, "upgrade", "f94a53da8bc4")
    assert initial.returncode == 0, initial.stderr
    with closing(sqlite3.connect(original)) as db, db:
        db.executemany("INSERT INTO cases(id,case_number,occurred_time,description) VALUES (?,?,?,?)", [
            (1, "SYNTHETIC-V60-A", "2026-09-27", "升级前事实甲"),
            (2, "SYNTHETIC-V60-B", "2026-09-27", "升级前事实乙"),
        ])
        db.execute("INSERT INTO chain_links(id,case_id_a,case_id_b,link_type,status,confidence,distance_km,time_diff_days,confirmed_by) "
                   "VALUES (1,1,2,'upstream_transport','confirmed',0.5,2.0,1,'历史复核人')")
    with closing(sqlite3.connect(original)) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    upgraded = migrate(original, "upgrade", "v60c01")
    assert upgraded.returncode == 0, upgraded.stderr
    with closing(sqlite3.connect(original)) as db, db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "v60c01"
        assert db.execute("SELECT status,confirmed_by,source_hash_a,source_hash_b FROM chain_links").fetchone() == (
            "confirmed", "历史复核人", None, None)
        assert db.execute("SELECT description FROM cases WHERE id=1").fetchone()[0] == "升级前事实甲"
        db.execute("UPDATE cases SET description='升级后新增事实' WHERE id=1")
        db.execute("INSERT INTO case_tips(case_id,content,verification_status) VALUES (1,'升级后未核实线索','pending')")
        before = list(db.iterdump())
    refused = migrate(original, "downgrade", "f94a53da8bc4")
    assert refused.returncode != 0
    assert "restore_compatible_backup_required_for_chain_version_downgrade" in refused.stderr
    with closing(sqlite3.connect(original)) as db:
        assert list(db.iterdump()) == before
    with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(restored)) as target:
        source.backup(target)
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "f94a53da8bc4"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    upgraded_again = migrate(restored, "upgrade", "v60c01")
    assert upgraded_again.returncode == 0, upgraded_again.stderr
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute("SELECT status,confirmed_by FROM chain_links").fetchone() == ("confirmed", "历史复核人")
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with closing(sqlite3.connect(original)) as db:
        assert db.execute("SELECT description FROM cases WHERE id=1").fetchone()[0] == "升级后新增事实"
        assert db.execute("SELECT content FROM case_tips").fetchone()[0] == "升级后未核实线索"
