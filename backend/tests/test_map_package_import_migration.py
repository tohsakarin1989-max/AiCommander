"""Migration roundtrip on a fresh disposable database, never application data."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from contextlib import closing


def test_map_import_migration_upgrade_downgrade_preserves_existing_tables(tmp_path):
    database = tmp_path / 'migration.sqlite'
    environment = {**os.environ, 'DATABASE_URL': f'sqlite:///{database}', 'ENABLE_VECTOR_DB': 'false'}
    backend = Path(__file__).resolve().parents[1]
    def migrate(direction, revision):
        result = subprocess.run([sys.executable, '-m', 'alembic', direction, revision],
            cwd=backend, env=environment, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
    # This roundtrip covers the import-table migration, not future revisions
    # that deliberately disallow destructive schema narrowing.
    migrate('upgrade', 'e72af1041484')
    with closing(sqlite3.connect(database)) as db, db:
        columns = {r[1] for r in db.execute('PRAGMA table_info(map_package_imports)')}
        assert {'manifest_hash', 'status', 'lease_token', 'lease_expires_at'} <= columns
        db.execute("INSERT INTO operational_areas(code,name,is_default,status) VALUES ('sentinel','保留测试厂区',0,'active')")
    migrate('downgrade', 'd619e0f20373')
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT count(*) FROM operational_areas WHERE code='sentinel'").fetchone()[0] == 1
        assert db.execute("SELECT name FROM sqlite_master WHERE name='map_package_imports'").fetchone() is None
    migrate('upgrade', 'head')


def test_capacity_downgrade_refused_and_compatible_backup_restores(tmp_path):
    database = tmp_path / 'current.sqlite'
    backup = tmp_path / 'compatible.sqlite'
    restored = tmp_path / 'restored.sqlite'
    backend = Path(__file__).resolve().parents[1]
    environment = {**os.environ, 'DATABASE_URL': f'sqlite:///{database}', 'ENABLE_VECTOR_DB': 'false'}

    def migrate(direction, revision):
        return subprocess.run([sys.executable, '-m', 'alembic', direction, revision],
            cwd=backend, env=environment, capture_output=True, text=True, timeout=60)

    result = migrate('upgrade', 'e72af1041484')
    assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("INSERT INTO operational_areas(code,name,is_default,status) VALUES ('retained','升级前业务数据',0,'active')")
    with closing(sqlite3.connect(database)) as db, closing(sqlite3.connect(backup)) as target:
        db.backup(target)
    # Pin the capacity revision: later versions have their own rollback gates.
    result = migrate('upgrade', 'f830b2152595')
    assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("INSERT INTO operational_areas(code,name,is_default,status) VALUES ('new-data','升级后业务数据',0,'active')")
        before = list(db.iterdump())
    result = migrate('downgrade', 'e72af1041484')
    assert result.returncode != 0
    assert 'restore_compatible_backup_required_for_map_capacity_downgrade' in result.stderr
    with closing(sqlite3.connect(database)) as db:
        assert list(db.iterdump()) == before
    # Restore into a separate database: never erase post-upgrade business data.
    with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(restored)) as target:
        source.backup(target)
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == 'e72af1041484'
        assert db.execute("SELECT name FROM operational_areas WHERE code='retained'").fetchone()[0] == '升级前业务数据'
        assert db.execute("SELECT count(*) FROM operational_areas WHERE code='new-data'").fetchone()[0] == 0
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT name FROM operational_areas WHERE code='new-data'").fetchone()[0] == '升级后业务数据'
