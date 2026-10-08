"""v6.3 actual migrations and isolated SQLite/PostgreSQL retrieval acceptance."""
import os
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_history_index import CaseHistoryFragment
from app.models.map_foundation import OperationalArea
from app.services.case_history_index_service import CaseHistoryIndexService
from app.services.case_history_retrieval import CaseHistoryRetrieval
from tests.test_facility_migration_v62 import migrate


def exercise_upgrade(url, monkeypatch):
    migrate(url, 'v62f01')
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO cases(id,case_number,description,operational_area_id) "
                                "VALUES(1,'SYN63-STRUCTURAL','夜里。',1)"))
    migrate(url, 'head')
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == 'v75r01'
        assert connection.scalar(text('SELECT description FROM cases WHERE id=1')) == '夜里。'
    model = SimpleNamespace(state='ready', model_version='synthetic-v63-pg',
        encode=lambda value: [1., 0.] if value == '另一种完全不同表述。' else [0., 1.])
    monkeypatch.setattr('app.services.local_embedding_service.get_local_embedder', lambda: model)
    query_model = SimpleNamespace(state='ready', model_version=model.model_version, encode=lambda _: [1., 0.])
    monkeypatch.setattr('app.services.case_history_retrieval.get_local_embedder', lambda: query_model)
    with Session(engine) as db:
        db.add(OperationalArea(id=2, code='SYN63-HIDDEN', name='合成未授权区'))
        db.flush()
        db.add_all([Case(id=2, case_number='SYN63-LEXICAL', description='专用甲乙丙。', operational_area_id=1),
                    Case(id=3, case_number='SYN63-SEMANTIC', description='另一种完全不同表述。', operational_area_id=1),
                    Case(id=4, case_number='SYN63-HIDDEN', description='专用甲乙丙。', operational_area_id=2)])
        db.commit()
        CaseHistoryIndexService.reconcile_batch(db)
        db.commit()
        db.info['authorized_area_ids'] = (1,)
        statements = []
        def capture(_conn, _cursor, statement, *_args):
            statements.append(statement)
        event.listen(engine, 'before_cursor_execute', capture)
        try:
            result = CaseHistoryRetrieval.search(db, query='专用甲乙丙', limit=3,
                query_conditions={('time_condition', '夜间', 'stated')})
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
        assert result['state'] == 'ready'
        assert result['coverage']['branch_counts'] == {'structural': 1, 'lexical': 1, 'semantic': 1}
        assert {item['case_id'] for item in result['items']} == {1, 2, 3}
        assert result['coverage']['authorized_cases'] == 3 and 'SYN63-HIDDEN' not in str(result)
        assert not any(statement.lstrip().split()[0].lower() in {'insert', 'update', 'delete'} for statement in statements)
        if engine.dialect.name == 'postgresql':
            assert any('<=>' in statement and 'LIMIT' in statement for statement in statements)
        original_count = db.query(CaseHistoryFragment).count()
        db.info['authorized_area_ids'] = ()
        assert db.query(CaseHistoryFragment).count() == 0
        db.info['authorized_area_ids'] = None
        db.delete(db.get(Case, 4))
        db.commit()
        assert db.query(CaseHistoryFragment).count() == original_count
    migrate(url, 'head')
    engine.dispose()


def test_v63_sqlite_upgrade_and_fragment_queries(tmp_path, monkeypatch):
    exercise_upgrade(f'sqlite:///{tmp_path / "synthetic-v63.sqlite"}', monkeypatch)


def test_v63_disposable_postgres_queries_and_restore(monkeypatch):
    value = os.environ.get('AIC_V63_DISPOSABLE_PG_URL')
    if not value:
        pytest.skip('disposable PostgreSQL explicitly not requested')
    url = make_url(value)
    container = os.environ['AIC_V63_DISPOSABLE_PG_CONTAINER']
    assert url.host == '127.0.0.1' and url.database == 'aic_v63_migration'
    assert url.username == 'aic_v63_synthetic' and container.startswith('aic-v63-fragments-')
    assert os.environ.get('AIC_V63_DISPOSABLE_PG_CONFIRMED') == '1'
    exercise_upgrade(value, monkeypatch)
    backup = subprocess.run(['docker', 'exec', container, 'pg_dump', '-U', url.username,
        '-d', url.database, '--no-owner', '--no-privileges'], capture_output=True, timeout=60)
    assert backup.returncode == 0, backup.stderr.decode()
    engine = create_engine(url)
    try:
        with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
            db.execute(text('CREATE DATABASE aic_v63_restore'))
        restored = subprocess.run(['docker', 'exec', '-i', container, 'psql', '-U', url.username,
            '-d', 'aic_v63_restore', '-v', 'ON_ERROR_STOP=1'], input=backup.stdout, capture_output=True, timeout=60)
        assert restored.returncode == 0, restored.stderr.decode()
        restored_engine = create_engine(url.set(database='aic_v63_restore'))
        try:
            with restored_engine.connect() as db:
                assert db.scalar(text('SELECT version_num FROM alembic_version')) == 'v75r01'
                assert db.scalar(text('SELECT count(*) FROM cases')) == 3
                assert db.scalar(text('SELECT count(*) FROM case_history_fragments')) > 3
                assert db.scalar(text('SELECT count(*) FROM case_history_postings')) > 3
                assert db.scalar(text('SELECT count(*) FROM case_history_fragments WHERE embedding IS NOT NULL')) > 3
                assert db.scalar(text('SELECT description FROM cases WHERE id=1')) == '夜里。'
        finally:
            restored_engine.dispose()
    finally:
        engine.dispose()


def test_v63_existing_disposable_postgres_mixed_dimensions_are_isolated(monkeypatch):
    value = os.environ.get('AIC_V63_DISPOSABLE_PG_URL')
    if not value:
        pytest.skip('disposable PostgreSQL explicitly not requested')
    url = make_url(value)
    assert url.host == '127.0.0.1' and url.database == 'aic_v63_migration'
    assert url.username == 'aic_v63_synthetic' and os.environ.get('AIC_V63_DISPOSABLE_PG_CONFIRMED') == '1'
    model = SimpleNamespace(state='ready', model_version='synthetic-v63-pg', encode=lambda _: [1., 0.])
    monkeypatch.setattr('app.services.case_history_retrieval.get_local_embedder', lambda: model)
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            db.info['authorized_area_ids'] = (1,)
            row = db.scalar(select(CaseHistoryFragment).where(CaseHistoryFragment.case_id == 3,
                CaseHistoryFragment.field == 'description'))
            assert row is not None  # This test deliberately uses the database just created above.
            db.execute(text('UPDATE case_history_fragments SET embedding = CAST(:values AS vector), dimension = 2 WHERE id = :id'),
                       {'values': '[1,0,0]', 'id': row.id})
            result = CaseHistoryRetrieval.search(db, query='QZXW')
            assert result['items'] == [] and result['semantic_index_state'] == 'partial'
            assert result['coverage']['vector_missing'] == 1
            db.rollback()
    finally:
        engine.dispose()


def test_v63_existing_disposable_postgres_source_change_during_embedding_rolls_back(monkeypatch):
    value = os.environ.get('AIC_V63_DISPOSABLE_PG_URL')
    if not value:
        pytest.skip('disposable PostgreSQL explicitly not requested')
    url = make_url(value)
    assert url.host == '127.0.0.1' and url.database == 'aic_v63_migration'
    assert url.username == 'aic_v63_synthetic' and os.environ.get('AIC_V63_DISPOSABLE_PG_CONFIRMED') == '1'
    from app.models.case_history_index import CaseHistoryIndex
    from app.services.case_source_service import CaseSourceService
    engine = create_engine(url)
    statements, calls, background_connection = [], [], None
    def capture(_conn, _cursor, statement, *_args):
        if _conn is background_connection:
            statements.append(statement)
    def encode(_value):
        # A source editor must be able to commit while the background model runs.
        assert not any('FOR UPDATE' in statement for statement in statements)
        if not calls:
            with Session(engine) as editor:
                editor.execute(text("SET LOCAL lock_timeout = '1s'"))
                case = editor.get(Case, 1)
                case.description += '新增并发更正。'
                CaseSourceService.capture_change(editor, case)
                editor.commit()
        calls.append(True)
        return [1., 0.]
    model = SimpleNamespace(state='ready', model_version='synthetic-concurrent-v63', encode=encode)
    monkeypatch.setattr('app.services.local_embedding_service.get_local_embedder', lambda: model)
    try:
        with Session(engine) as db:
            parent = db.scalar(select(CaseHistoryIndex).where(CaseHistoryIndex.case_id == 1))
            original_hash = parent.source_hash
            case = db.get(Case, 1)
            background_connection = db.connection()
            event.listen(engine, 'before_cursor_execute', capture)
            try:
                with pytest.raises(ValueError, match='history_source_changed'):
                    CaseHistoryIndexService.rebuild_case(db, case)
            finally:
                event.remove(engine, 'before_cursor_execute', capture)
                db.rollback()
            assert calls and any('FOR UPDATE' in statement for statement in statements)
            assert db.scalar(select(CaseHistoryIndex.source_hash).where(CaseHistoryIndex.case_id == 1)) == original_hash
            assert db.scalar(select(Case.description).where(Case.id == 1)).endswith('新增并发更正。')
    finally:
        engine.dispose()
