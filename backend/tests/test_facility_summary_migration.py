"""Incremental upgrade and separate recovery preserve post-upgrade business data."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_facility_summary_upgrade_and_separate_backup_restore(tmp_path):
    database, backup = tmp_path / 'v54.sqlite', tmp_path / 'v53.sqlite'
    environment = {**os.environ, 'DATABASE_URL': f'sqlite:///{database}', 'ENABLE_VECTOR_DB': 'false'}
    backend = Path(__file__).resolve().parents[1]

    def migrate(direction, revision):
        return subprocess.run([sys.executable, '-m', 'alembic', direction, revision], cwd=backend,
            env=environment, capture_output=True, text=True, timeout=60)

    original = migrate('upgrade', 'e83f42c97ab3')
    assert original.returncode == 0, original.stderr
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("INSERT INTO cases(case_number,occurred_time,description) VALUES ('SYNTHETIC-V54','2026-09-25','升级前事实')")
    with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    upgraded = migrate('upgrade', 'f94a53da8bc4')
    assert upgraded.returncode == 0, upgraded.stderr
    with closing(sqlite3.connect(database)) as db, db:
        assert db.execute('SELECT description FROM cases').fetchone()[0] == '升级前事实'
        assert {row[1] for row in db.execute('PRAGMA table_info(facility_derived_summaries)')} >= {
            'asset_id', 'revision', 'payload', 'content_sha256', 'changes'}
        db.execute("UPDATE cases SET description='升级后新增事实'")
        before = list(db.iterdump())
    refused = migrate('downgrade', 'e83f42c97ab3')
    assert refused.returncode != 0 and 'restore_compatible_backup_required_for_facility_downgrade' in refused.stderr
    with closing(sqlite3.connect(database)) as db:
        assert list(db.iterdump()) == before
    restored = tmp_path / 'separate-v53.sqlite'
    with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(restored)) as target:
        source.backup(target)
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == 'e83f42c97ab3'
    with closing(sqlite3.connect(database)) as db:
        assert db.execute('SELECT description FROM cases').fetchone()[0] == '升级后新增事实'
