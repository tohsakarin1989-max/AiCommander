"""Opt-in real component check. Only a named disposable loopback database is accepted."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
from threading import Barrier

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def test_v70_postgres_upgrade_concurrent_save_fresh_install_and_restore():
    value = os.environ.get('AIC_V70_DISPOSABLE_PG_URL')
    if not value:
        pytest.skip('explicit disposable PostgreSQL not requested')
    url = make_url(value)
    container = os.environ.get('AIC_V70_DISPOSABLE_PG_CONTAINER')
    assert url.host == '127.0.0.1' and url.database == 'aic_v70_upgrade'
    assert url.username == 'aic_v70_synthetic' and container == 'aic-v70-validation-pg'
    assert os.environ.get('AIC_V70_DISPOSABLE_PG_CONFIRMED') == '1'
    from alembic import command
    from alembic.config import Config
    from app.models.case import Case
    from app.models.case_source import EvidenceObject
    from app.models.case_submission import CaseSubmissionReceipt
    from app.services.case_submission_service import create_case_submission, submission_status
    from init_fresh_db import initialize_empty_database
    engine = create_engine(url)

    def migrate(target):
        with engine.begin() as connection:
            config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
            config.attributes['connection'] = connection
            command.upgrade(config, target)

    with engine.connect() as db:
        assert db.scalar(text("SELECT to_regclass('public.cases')")) is None
    migrate('v65r01')
    with engine.begin() as db:
        db.execute(text("INSERT INTO cases(case_number,description,operational_area_id) VALUES ('SYN-V70-BEFORE','升级前原始合成记录',1)"))
        db.execute(text("INSERT INTO users(id,username,display_name,password_hash,role) VALUES (1,'v70-synthetic','合成管理员','not-a-real-login','admin')"))
    migrate('v70s01')  # This historical receipt probe freezes its own upgrade target.
    barrier = Barrier(4)

    def save(_):
        with Session(engine) as db:
            db.info.update(principal_user_id=1, authorized_area_ids=None)
            barrier.wait(timeout=15)
            return create_case_submission(db, key='concurrent-v70',
                request_payload={'description': '升级后合成录入'},
                values={'case_number': None, 'description': '升级后合成录入', 'operational_area_id': 1}).id

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(save, range(4)))
    assert len(set(ids)) == 1
    with Session(engine) as db:
        db.info.update(principal_user_id=1, authorized_area_ids=None)
        assert db.query(Case).count() == 2
        assert db.query(CaseSubmissionReceipt).count() == 1
        assert submission_status(db, 'concurrent-v70') == {'status': 'completed', 'case_id': ids[0]}
        db.add(EvidenceObject(storage_key='synthetic-v70-original', sha256='a' * 64,
            media_type='text/plain', sensitivity='internal', availability='available', content=b'synthetic original bytes'))
        db.commit()
    backup = subprocess.run(['docker', 'exec', container, 'pg_dump', '-U', url.username,
        '-d', url.database, '--no-owner', '--no-privileges'], capture_output=True, timeout=60)
    assert backup.returncode == 0, backup.stderr.decode()
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
        db.execute(text('CREATE DATABASE aic_v70_restore'))
        db.execute(text('CREATE DATABASE aic_v70_fresh'))
    restored = subprocess.run(['docker', 'exec', '-i', container, 'psql', '-U', url.username,
        '-d', 'aic_v70_restore', '-v', 'ON_ERROR_STOP=1'], input=backup.stdout, capture_output=True, timeout=60)
    assert restored.returncode == 0, restored.stderr.decode()
    restored_engine = create_engine(url.set(database='aic_v70_restore'))
    with restored_engine.connect() as db:
        assert db.scalar(text('SELECT version_num FROM alembic_version')) == 'v70s01'
        assert db.scalar(text('SELECT count(*) FROM cases')) == 2
        assert db.scalar(text('SELECT count(*) FROM case_submission_receipts')) == 1
        assert bytes(db.scalar(text("SELECT content FROM evidence_objects WHERE storage_key='synthetic-v70-original'"))) == b'synthetic original bytes'
    fresh_url = url.set(database='aic_v70_fresh').render_as_string(hide_password=False)
    assert initialize_empty_database(fresh_url, confirmed=True) == 'v75r01'
    with pytest.raises(ValueError, match='target_not_empty'):
        initialize_empty_database(fresh_url, confirmed=True)
    restored_engine.dispose()
    engine.dispose()
