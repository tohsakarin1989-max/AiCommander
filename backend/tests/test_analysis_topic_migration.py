"""Additive topic upgrade; separate restored baseline preserves the upgraded data."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_topic_migration_backup_and_non_destructive_rollback(tmp_path):
    database = tmp_path / 'v53.sqlite'
    backup = tmp_path / 'v52-backup.sqlite'
    environment = {**os.environ, 'DATABASE_URL': f'sqlite:///{database}', 'ENABLE_VECTOR_DB': 'false'}
    backend = Path(__file__).resolve().parents[1]

    def migrate(direction, revision):
        return subprocess.run([sys.executable, '-m', 'alembic', direction, revision],
            cwd=backend, env=environment, capture_output=True, text=True, timeout=60)

    initial = migrate('upgrade', 'd72e31b86fa2')
    assert initial.returncode == 0, initial.stderr
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("INSERT INTO cases(case_number,occurred_time,description) VALUES ('SYNTHETIC-TOPIC-UPGRADE','2026-09-21','升级前原始记录')")
    with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    upgraded = migrate('upgrade', 'e83f42c97ab3')
    assert upgraded.returncode == 0, upgraded.stderr
    with closing(sqlite3.connect(database)) as db, db:
        assert db.execute('SELECT description FROM cases').fetchone()[0] == '升级前原始记录'
        assert {row[1] for row in db.execute('PRAGMA table_info(analysis_topics)')} >= {
            'filters', 'scope_version', 'lease_token', 'paused', 'next_refresh_at'}
        assert {row[1] for row in db.execute('PRAGMA table_info(topic_snapshots)')} >= {
            'topic_id', 'revision', 'content_sha256', 'payload', 'changes'}
        db.execute("UPDATE cases SET description='升级后新增业务记录'")
        before = list(db.iterdump())
    refused = migrate('downgrade', 'd72e31b86fa2')
    assert refused.returncode != 0
    assert 'restore_compatible_backup_required_for_topic_downgrade' in refused.stderr
    with closing(sqlite3.connect(database)) as db:
        assert list(db.iterdump()) == before
    restored = tmp_path / 'separate-restored-v52.sqlite'
    with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(restored)) as target:
        source.backup(target)
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == 'd72e31b86fa2'
        assert db.execute('SELECT description FROM cases').fetchone()[0] == '升级前原始记录'
    with closing(sqlite3.connect(database)) as db:
        assert db.execute('SELECT description FROM cases').fetchone()[0] == '升级后新增业务记录'
