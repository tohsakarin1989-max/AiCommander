"""Disposable migration, data-preserving refusal and separate backup restoration."""
from contextlib import closing
import sqlite3
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
import pytest
from tests.test_result_material_migration_v65 import migrate


def test_v9_sqlite_upgrade_and_separate_restore(tmp_path):
    path, backup = tmp_path / 'v9.sqlite', tmp_path / 'v84.sqlite'
    url = f'sqlite:///{path}'
    result = migrate(url, 'upgrade', 'v80f01')
    assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO cases(case_number,description) VALUES('V9-ORIGINAL','迁移前原始资料')")
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    for direction, revision in [('upgrade', 'v94o01'), ('downgrade', 'v80f01'), ('upgrade', 'v94o01')]:
        result = migrate(url, direction, revision)
        assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute('SELECT description FROM cases').fetchone()[0] == '迁移前原始资料'
        db.execute("INSERT INTO output_templates(id,operational_area_id,kind,name,version,configuration) "
                   "VALUES('v9',1,'case_ledger','合成模板',1,'{}')")
        db.execute("INSERT INTO cases(case_number,description) VALUES('V9-NEW','升级后新增原始资料')")
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    result = migrate(url, 'downgrade', 'v80f01')
    assert result.returncode != 0 and 'output_templates_require_compatible_backup' in result.stderr
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT count(*) FROM cases').fetchone()[0] == 2
    with closing(sqlite3.connect(backup)) as restored:
        assert restored.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert restored.execute('SELECT description FROM cases').fetchone()[0] == '迁移前原始资料'
        assert restored.execute('SELECT version_num FROM alembic_version').fetchone()[0] == 'v80f01'


def test_v9_postgres_sources_concurrency_and_native_restore(record_property):
    value = os.environ.get('AIC_V9_PG_URL')
    if not value:
        pytest.skip('requires explicitly isolated PostgreSQL')
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from app.models.case import Case
    from app.models.case_import import CaseImportSourceRecord
    from app.services.case_import_table import parse_case_table
    from app.services.case_source_import import import_source_table
    parsed = make_url(value)
    container = os.environ.get('AIC_V9_PG_CONTAINER')
    assert parsed.host == '127.0.0.1' and parsed.database == 'aic_v9_validation'
    assert container == 'aic-v9-validation-20261009'
    engine = create_engine(value)
    with engine.connect() as db:
        assert db.scalar(text("SELECT to_regclass('public.cases')")) is None
    before = migrate(value, 'upgrade', 'v80f01')
    assert before.returncode == 0, before.stderr
    with engine.begin() as db:
        db.execute(text("INSERT INTO cases(case_number,description) VALUES('V9-PG-LEGACY','升级前合成事实')"))
    after = migrate(value, 'upgrade', 'v94o01')
    assert after.returncode == 0, after.stderr
    content = '源记录键,发现时间,地点,简要案情\nTEST-1,2026-10-09,路口,并发合成资料\n'.encode()
    table = parse_case_table('synthetic.csv', content)
    def ingest(_):
        with Session(engine, autoflush=False) as db:
            return import_source_table(db, table=table, content=content, area_id=1,
                source_key='PG合成来源', source_revision='1', time_zone='Asia/Shanghai')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(ingest, range(2)))
    assert sum(row['created'] for row in results) == 1
    assert sum(bool(row['replayed']) for row in results) == 1
    with Session(engine) as db:
        assert db.query(CaseImportSourceRecord).count() == 1
        assert db.query(Case).count() == 2
        db.info['authorized_area_ids'] = ()
        assert db.query(CaseImportSourceRecord).count() == 0
    def docker(*args, content=None):
        result = subprocess.run(['docker', 'exec', '-i', container, *args], input=content,
                                capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr.decode()
        return result.stdout
    backup = docker('pg_dump', '-U', 'postgres', '-d', 'aic_v9_validation', '-Fc', '--no-owner', '--no-privileges')
    docker('createdb', '-U', 'postgres', 'aic_v9_restore')
    docker('pg_restore', '-U', 'postgres', '-d', 'aic_v9_restore', '--exit-on-error', '--no-owner', '--no-privileges', content=backup)
    restored = create_engine(parsed.set(database='aic_v9_restore'))
    with engine.connect() as source, restored.connect() as target:
        for table_name in ('cases', 'case_import_source_records', 'case_import_batches', 'case_import_rows',
                           'case_revisions', 'source_references', 'evidence_objects'):
            statement = text(f'SELECT row_to_json(t) FROM {table_name} t ORDER BY id')
            assert source.execute(statement).scalars().all() == target.execute(statement).scalars().all()
        assert target.scalar(text('SELECT version_num FROM alembic_version')) == 'v94o01'
    import hashlib
    record_property('backup_sha256', hashlib.sha256(backup).hexdigest())
    record_property('restored_original_cases', 2)
    record_property('concurrent_duplicate_creations', 0)
    restored.dispose()
    engine.dispose()
