"""Additive upgrade and separately restored backup; existing records preserved."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import pytest


def test_v64_upgrade_and_separate_restore_preserve_both_versions(tmp_path):
    target = tmp_path / 'v64-test.sqlite'
    backup = tmp_path / 'v63-backup.sqlite'
    environment = {**os.environ, 'DATABASE_URL': f'sqlite:///{target}', 'ENABLE_VECTOR_DB': 'false'}
    backend = Path(__file__).resolve().parents[1]
    def migrate(direction, revision):
        result = subprocess.run([sys.executable, '-m', 'alembic', direction, revision], cwd=backend,
            env=environment, capture_output=True, text=True, timeout=60)
        return result
    initial = migrate('upgrade', 'v63h01')
    assert initial.returncode == 0, initial.stderr
    with closing(sqlite3.connect(target)) as db, db:
        db.execute("INSERT INTO cases(case_number,description,time_precision) VALUES ('V64-SYNTHETIC','升级前原文','unknown')")
    with closing(sqlite3.connect(target)) as source, closing(sqlite3.connect(backup)) as destination:
        source.backup(destination)
    upgraded = migrate('upgrade', 'v64t01')
    assert upgraded.returncode == 0, upgraded.stderr
    with closing(sqlite3.connect(target)) as db, db:
        assert db.execute('SELECT description FROM cases').fetchone()[0] == '升级前原文'
        columns = {row[1] for row in db.execute('PRAGMA table_info(analysis_topics)')}
        assert {'question', 'question_kind', 'definition_revision', 'window', 'latest_job_id'} <= columns
        before = db.execute('SELECT revision FROM topic_data_revision').fetchone()[0]
        db.execute("UPDATE cases SET description='升级后新增资料'")
        assert db.execute('SELECT revision FROM topic_data_revision').fetchone()[0] > before
    refused = migrate('downgrade', 'v63h01')
    assert refused.returncode != 0 and 'restore_compatible_backup_required_for_topic_v64' in refused.stderr
    restored = tmp_path / 'separate-v63-restored.sqlite'
    with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(restored)) as destination:
        source.backup(destination)
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == 'v63h01'
        assert db.execute('SELECT description FROM cases').fetchone()[0] == '升级前原文'
    with closing(sqlite3.connect(target)) as db:
        assert db.execute('SELECT description FROM cases').fetchone()[0] == '升级后新增资料'


def test_v64_disposable_postgres_migration_fence_resume_and_restore(monkeypatch):
    """Explicit disposable database only; no default/configured DB is ever used."""
    value = os.environ.get('AIC_V64_DISPOSABLE_PG_URL')
    if not value:
        pytest.skip('explicit disposable PostgreSQL not requested')
    from sqlalchemy import create_engine, text, update
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import OperationalError
    from app.models.analysis_topic import AnalysisTopic, TopicSnapshot, TopicRefreshChunk
    from app.models.case import Case
    from app.models.case_pipeline import OutboxEvent
    from app.services import analysis_topic_service as topics
    from app.services import profile_aggregate_jobs as jobs
    from app.services.topic_revision_fence import current_revision
    from tests.test_facility_migration_v62 import migrate
    url = make_url(value)
    container = os.environ.get('AIC_V64_DISPOSABLE_PG_CONTAINER', '')
    assert url.host == '127.0.0.1' and url.database == 'aic_v64_topics'
    assert container.startswith('aic-v65-validation-')
    assert os.environ.get('AIC_V64_DISPOSABLE_PG_CONFIRMED') == '1'
    migrate(value, 'v63h01')
    engine = create_engine(value)
    with engine.begin() as db:
        db.execute(text("INSERT INTO cases(id,case_number,description,operational_area_id) VALUES (1,'V64-PG-SYNTHETIC','升级前原文',1)"))
        db.execute(text("INSERT INTO users(id,username,display_name,password_hash,role) VALUES(1,'v64-synthetic','合成验证','not-a-login','admin')"))
        db.execute(text("SELECT setval(pg_get_serial_sequence('cases','id'),1)"))
        db.execute(text("SELECT setval(pg_get_serial_sequence('users','id'),1)"))
    backup = subprocess.run(['docker', 'exec', container, 'pg_dump', '-U', url.username,
        '-d', url.database, '--no-owner', '--no-privileges'], capture_output=True, timeout=60)
    assert backup.returncode == 0, backup.stderr.decode()
    migrate(value, 'v64t01')
    monkeypatch.setattr(jobs, 'PAGE_SIZE', 1)
    with Session(engine, autoflush=False) as db:
        db.info['principal_user_id'] = 1
        db.add_all([Case(case_number=f'V64-PG-{i}', description='合成资料', operational_area_id=1) for i in (2, 3)])
        db.commit()
        created = topics.create_topic(db, '合成PG续跑', {})
        topic = db.get(AnalysisTopic, created['id'])
        job = jobs.create_aggregate_job(db, {}, topic=topic)
        db.commit()
        original = jobs._case_page
        changed = []
        def edit_during_scan(session, event, data, deadline):
            original(session, event, data, deadline)
            if not changed:
                with engine.begin() as editor:
                    editor.execute(text("SET LOCAL lock_timeout = '1s'"))
                    editor.execute(text("UPDATE cases SET description='扫描时并发新增资料' WHERE id=1"))
                changed.append(True)
        monkeypatch.setattr(jobs, '_case_page', edit_during_scan)
        result = jobs.process_aggregate_job(db, job['id'], max_pages=1)
        assert result['status'] == 'superseded' and changed
        assert db.query(TopicSnapshot).count() == 0 and db.query(TopicRefreshChunk).count() == 0
        monkeypatch.setattr(jobs, '_case_page', original)
        topics.request_refresh(db, topic.id)
        topic = db.get(AnalysisTopic, topic.id, populate_existing=True)
        resumed = jobs.create_aggregate_job(db, {}, topic=topic)
        db.commit()
        first = jobs.process_aggregate_job(db, resumed['id'], max_pages=1)
        assert first['status'] == 'running' and first['scanned_cases'] == 1
        topic_id = topic.id
    # New process/session has no access to previous Python accumulator.
    with Session(engine, autoflush=False) as db:
        db.info['principal_user_id'] = 1
        for _ in range(20):
            result = jobs.process_aggregate_job(db, resumed['id'], max_pages=1)
            if result['status'] != 'running':
                break
        assert result['status'] == 'updated'
        assert topics.read_topic(db, topic_id)['snapshot']['aggregate']['coverage']['scanned_cases'] == 3
        db.rollback()
        generation = current_revision(db, lock=True)
        with engine.connect() as editor:
            editor.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError):
                editor.execute(text("UPDATE cases SET description='must-not-cross-fence' WHERE id=1"))
            editor.rollback()
        assert current_revision(db) == generation
        db.rollback()
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
        db.execute(text('CREATE DATABASE aic_v64_topics_restore'))
    restored = subprocess.run(['docker', 'exec', '-i', container, 'psql', '-U', url.username,
        '-d', 'aic_v64_topics_restore', '-v', 'ON_ERROR_STOP=1'], input=backup.stdout, capture_output=True, timeout=60)
    assert restored.returncode == 0, restored.stderr.decode()
    restore_engine = create_engine(url.set(database='aic_v64_topics_restore'))
    with restore_engine.connect() as db:
        assert db.scalar(text('SELECT version_num FROM alembic_version')) == 'v63h01'
        assert db.scalar(text('SELECT description FROM cases WHERE id=1')) == '升级前原文'
    with engine.connect() as db:
        assert db.scalar(text('SELECT description FROM cases WHERE id=1')) == '扫描时并发新增资料'
    restore_engine.dispose()
    engine.dispose()


@pytest.mark.parametrize('change_kind', ['source', 'definition'])
def test_v64_postgres_publication_fence_after_evidence_reads(monkeypatch, change_kind):
    """A separately prepared disposable DB; writes during validation must not block."""
    value = os.environ.get('AIC_V64_DISPOSABLE_PG_URL')
    if not value:
        pytest.skip('explicit disposable PostgreSQL not requested')
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from app.models.analysis_topic import AnalysisTopic, TopicSnapshot
    from app.services import analysis_topic_service as topics
    from app.services import profile_aggregate_jobs as jobs
    url = make_url(value)
    assert url.host == '127.0.0.1' and url.database == 'aic_v64_topics'
    assert os.environ.get('AIC_V64_DISPOSABLE_PG_CONFIRMED') == '1'
    engine = create_engine(value)
    from app.services.topic_revision_fence import install
    with engine.begin() as connection:
        install(connection)
    with Session(engine, autoflush=False) as db:
        db.info['principal_user_id'] = 1
        created = topics.create_topic(db, '合成最终发布并发检查', {})
        identifier = created['id']
        original = topics.validate_snapshot_access
        changed = []

        def concurrent_change(session, snapshot):
            original(session, snapshot)
            if changed:
                return
            with Session(engine, autoflush=False) as editor:
                editor.info['principal_user_id'] = 1
                editor.execute(text("SET LOCAL lock_timeout = '500ms'"))
                if change_kind == 'source':
                    editor.execute(text("UPDATE cases SET description=description || '合成新修订' WHERE id=1"))
                    editor.commit()
                else:
                    topics.update_topic(editor, identifier, question='并发修改的问题', expected_definition_revision=1)
            changed.append(True)

        monkeypatch.setattr(topics, 'validate_snapshot_access', concurrent_change)
        result = topics.refresh_topic(db, identifier)
        assert changed and result['status'] == 'superseded'
        assert db.query(TopicSnapshot).filter_by(topic_id=identifier).count() == 0
        topic = db.get(AnalysisTopic, identifier, populate_existing=True)
        assert topic.refresh_state == 'queued'
    engine.dispose()


def test_v64_postgres_writers_do_not_serialize_on_global_revision():
    value = os.environ.get('AIC_V64_DISPOSABLE_PG_URL')
    if not value:
        pytest.skip('explicit disposable PostgreSQL not requested')
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import OperationalError
    from app.services.topic_revision_fence import install, current_revision
    url = make_url(value)
    assert url.host == '127.0.0.1' and url.database == 'aic_v64_topics'
    assert os.environ.get('AIC_V64_DISPOSABLE_PG_CONFIRMED') == '1'
    engine = create_engine(value)
    with engine.begin() as connection:
        install(connection)
    with engine.connect() as first, engine.connect() as second:
        first.execute(text("SET LOCAL lock_timeout = '500ms'"))
        second.execute(text("SET LOCAL lock_timeout = '500ms'"))
        first.execute(text("UPDATE cases SET description=description WHERE id=1"))
        # The old AFTER trigger waited on the shared revision row here, then
        # deadlocked when the first writer next updated case 2.
        second.execute(text("UPDATE cases SET description=description WHERE id=2"))
        second.commit()
        first.execute(text("UPDATE cases SET description=description WHERE id=2"))
        first.commit()
    with Session(engine) as publication, engine.connect() as writer:
        generation = current_revision(publication, lock=True)
        writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(OperationalError):
            writer.execute(text("UPDATE cases SET description=description WHERE id=1"))
        writer.rollback()
        assert current_revision(publication) == generation
        publication.rollback()
    # Initial job admission must also wait for a source writer that incremented
    # the non-transactional sequence but has not yet committed its source rows.
    with Session(engine) as admission, engine.connect() as writer:
        writer.execute(text("UPDATE cases SET description=description WHERE id=1"))
        admission.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(OperationalError):
            current_revision(admission, lock=True)
        admission.rollback()
        writer.commit()
        assert current_revision(admission, lock=True) == current_revision(admission)
        admission.rollback()
    engine.dispose()
