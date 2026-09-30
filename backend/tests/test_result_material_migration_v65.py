"""Disposable SQLite/PostgreSQL upgrades; preserve old and new human records."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


def migrate(url, direction, revision):
    return subprocess.run([sys.executable, '-m', 'alembic', direction, revision],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=60,
        env={**os.environ, 'DATABASE_URL': url, 'ENABLE_VECTOR_DB': 'false',
             'AGENT_MODE': 'off', 'AGENT_USE_EXTERNAL_MODEL': 'false'})


def test_v65_sqlite_upgrade_empty_rollback_and_record_preservation(tmp_path):
    path, backup = tmp_path / 'materials.sqlite', tmp_path / 'v64.sqlite'
    url = f'sqlite:///{path}'
    before = migrate(url, 'upgrade', 'v64t01')
    assert before.returncode == 0, before.stderr
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO cases(case_number, description) VALUES ('V65-SYNTHETIC','升级前原记录')")
        db.execute("INSERT INTO users(id,username,display_name,password_hash,role) VALUES(1,'synthetic-v65','合成测试','not-a-login','admin')")
    with closing(sqlite3.connect(path)) as src, closing(sqlite3.connect(backup)) as dst:
        src.backup(dst)
    for direction, revision in [('upgrade', 'v65r01'), ('downgrade', 'v64t01'), ('upgrade', 'v65r01')]:
        result = migrate(url, direction, revision)
        assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO result_judgments(id,result_kind,result_id,content_sha256,decision,note,additional_sources,idempotency_key,created_by) "
                   "VALUES('synthetic-judgment','case','synthetic-result',?,'retain_reference','升级后人工意见','[]','synthetic-request',1)", ('a' * 64,))
        db.execute("UPDATE cases SET description='升级后补充原记录'")
    refused = migrate(url, 'downgrade', 'v64t01')
    assert refused.returncode != 0 and 'v65_materials_require_backup_before_downgrade' in refused.stderr
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT note FROM result_judgments').fetchone()[0] == '升级后人工意见'
        assert db.execute('SELECT description FROM cases').fetchone()[0] == '升级后补充原记录'
    with closing(sqlite3.connect(backup)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT description FROM cases').fetchone()[0] == '升级前原记录'
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == 'v64t01'


def test_v65_disposable_postgres_concurrent_idempotence_and_separate_restore():
    value = os.environ.get('AIC_V65_MATERIALS_PG_URL')
    if not value:
        pytest.skip('explicit disposable PostgreSQL not requested')
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from app.models.result_material import ResultJudgment, FacilityMaterial
    from app.services.result_catalog import read_result
    from app.services.result_judgment_service import record_judgment
    from app.services.facility_material_service import freeze_facility
    from tests.test_result_materials_v65 import saved_case, facility
    parsed = make_url(value)
    container = os.environ.get('AIC_V65_MATERIALS_PG_CONTAINER', '')
    assert parsed.host == '127.0.0.1' and parsed.database in {'aic_v65_materials', 'aic_v65_materials_final'}
    assert container.startswith('aic-v65-validation-')
    assert os.environ.get('AIC_V65_MATERIALS_PG_CONFIRMED') == '1'
    engine = create_engine(value)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('public.cases')")) is None
    initial = migrate(value, 'upgrade', 'v64t01')
    assert initial.returncode == 0, initial.stderr
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO cases(id,case_number,description,operational_area_id) VALUES(1,'V65-PG-SYNTHETIC','升级前原记录',1)"))
        connection.execute(text("INSERT INTO users(id,username,display_name,password_hash,role) VALUES(1,'v65-material','合成测试','not-a-login','admin')"))
        connection.execute(text("SELECT setval(pg_get_serial_sequence('cases','id'),1)"))
        connection.execute(text("SELECT setval(pg_get_serial_sequence('users','id'),1)"))
    backup = subprocess.run(['docker', 'exec', container, 'pg_dump', '-U', parsed.username,
        '-d', parsed.database, '--no-owner', '--no-privileges'], capture_output=True, timeout=60)
    assert backup.returncode == 0, backup.stderr.decode()
    upgrade = migrate(value, 'upgrade', 'v65r01')
    assert upgrade.returncode == 0, upgrade.stderr
    with Session(engine, autoflush=False) as db:
        db.info.update(principal_user_id=1, authorized_area_ids=None)
        _, result = saved_case(db, 'V65-PG-NEW-CASE')
        asset_id = facility(db).id
    def same_judgment(_):
        with Session(engine, autoflush=False) as db:
            db.info['principal_user_id'] = 1
            row, created = record_judgment(db, 'case', result['id'], content_sha256=result['content_sha256'],
                decision='retain_reference', note='合成并发人工判断', additional_sources=[], idempotency_key='pg-same-decision')
            identifier = row.id
            db.commit()
            return identifier, created
    def same_material(_):
        with Session(engine, autoflush=False) as db:
            db.info['principal_user_id'] = 1
            row, created = freeze_facility(db, asset_id, idempotency_key='pg-same-material')
            identifier = row.id
            db.commit()
            return identifier, created
    for action in (same_judgment, same_material):
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(action, range(2)))
        assert outcomes[0][0] == outcomes[1][0] and sum(created for _, created in outcomes) == 1
    with Session(engine) as db:
        db.info['principal_user_id'] = 1
        assert len(read_result(db, 'case', result['id'])['judgments']) == 1
        assert db.query(ResultJudgment).count() == db.query(FacilityMaterial).count() == 1
        db.execute(text("UPDATE cases SET description='升级后补充原记录' WHERE id=1"))
        db.commit()
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        restore_database = parsed.database + '_restore'
        connection.execute(text('CREATE DATABASE ' + restore_database))
    restored = subprocess.run(['docker', 'exec', '-i', container, 'psql', '-U', parsed.username,
        '-d', restore_database, '-v', 'ON_ERROR_STOP=1'], input=backup.stdout, capture_output=True, timeout=60)
    assert restored.returncode == 0, restored.stderr.decode()
    restoration = create_engine(parsed.set(database=restore_database))
    with restoration.connect() as connection:
        assert connection.scalar(text('SELECT description FROM cases WHERE id=1')) == '升级前原记录'
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == 'v64t01'
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT description FROM cases WHERE id=1')) == '升级后补充原记录'
        assert connection.scalar(text('SELECT count(*) FROM result_judgments')) == 1
    restoration.dispose()
    engine.dispose()
