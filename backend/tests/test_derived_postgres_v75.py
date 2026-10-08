"""Opt-in v7.5 checks on new databases in the approved loopback synthetic PG.

Run from an empty temporary working directory with an absolute PYTHONPATH, so
the application never reads a repository .env. This test does not start/stop
Docker, download models, reuse databases, or delete the retained evidence.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session


@pytest.mark.skipif(os.environ.get('AIC_V75_DISPOSABLE_PG') != '1',
                   reason='requires explicit disposable PostgreSQL v7.5 validation')
def test_v75_upgrade_vectors_retry_concurrency_and_restore(monkeypatch):
    password = os.environ.get('AIC_V70_SYNTHETIC_PASSWORD')
    assert password, 'only the disposable container password may be supplied'
    assert not (Path.cwd() / '.env').exists(), 'run from an empty temporary cwd'
    container, username = 'aic-v70-validation-pg', 'aic_v70_synthetic'
    inspected = subprocess.run(['docker', 'inspect', '--format',
        '{{json .HostConfig.PortBindings}}|{{.Config.Image}}|{{.State.Status}}', container],
        capture_output=True, check=True, timeout=20).stdout.decode().strip().split('|')
    assert json.loads(inspected[0]).get('5432/tcp') == [{'HostIp': '127.0.0.1', 'HostPort': '15470'}]
    assert inspected[1:] == ['aicommander-postgis-vector:16-0.8.6', 'running']
    names = [f'aic_v75_{kind}_{uuid4().hex[:12]}' for kind in ('upgrade', 'restore', 'fresh')]
    url = URL.create('postgresql+psycopg2', username=username, password=password,
                     host='127.0.0.1', port=15470, database='postgres')
    admin = create_engine(url)
    try:
        with admin.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
            for name in names:
                assert db.scalar(text('SELECT 1 FROM pg_database WHERE datname=:name'), {'name': name}) is None
                db.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()
    print('Synthetic v7.5 databases retained:', ', '.join(names), flush=True)
    engines = [create_engine(url.set(database=name),
        connect_args={'options': '-c statement_timeout=30000 -c lock_timeout=20000'}) for name in names]
    engine, restored, fresh = engines

    from alembic import command
    from alembic.config import Config
    from app.database import bind_principal_scope
    from app.models.case import Case
    from app.models.case_history_index import CaseHistoryFragment, CaseHistoryVectorReuse
    from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
    from app.models.case_source import CaseRevision
    from app.models.user import AuditLog
    from app.services import derived_operations as operations
    from app.services.case_history_index_debt import current_input_stamp
    from app.services.case_history_index_service import CaseHistoryIndexService
    from app.services.case_source_service import CaseSourceService
    from app.services.case_semantic_evidence import text_hash

    class Encoder:
        state, model_version, dimension, encoder_fingerprint = 'ready', 'v75-pg-synthetic', 2, 'config-1'
        def __init__(self):
            self.calls = []
        def encode(self, value):
            self.calls.append(value)
            return [1., 0.]
    encoder = Encoder()
    monkeypatch.setattr('app.services.local_embedding_service.get_local_embedder', lambda: encoder)

    def migrate(target, *, target_engine=engine, direction='upgrade'):
        root = Path(__file__).resolve().parents[1]
        config = Config(str(root / 'alembic.ini'))
        config.set_main_option('script_location', str(root / 'alembic'))
        with target_engine.begin() as connection:
            config.attributes['connection'] = connection
            getattr(command, direction)(config, target)

    def session(target=engine):
        db = Session(target, autoflush=False)
        bind_principal_scope(db, SimpleNamespace(user_id=1, role='admin'), method='POST')
        return db

    def seed_failed(db, case):
        row = OutboxEvent(id=str(uuid4()), event_type='case.history.index.retry',
            aggregate_type='case', aggregate_id=str(case.id),
            idempotency_key=f'history-index-retry:{case.id}',
            payload={**current_input_stamp(db, case), 'ordinary_failures': 3},
            status='failed', attempts=3, error='history_embedding_failed',
            available_at=datetime.now(timezone.utc))
        db.add(row)
        db.commit()
        return row.id

    def concurrent_retry(event_ids, request_id):
        # Each transaction observes failed/current before either state CAS.
        # This forces the real PG lock/unique-index conflict, not a serial replay.
        barrier, original = Barrier(len(event_ids)), operations._current
        def rendezvous(*args):
            current = original(*args)
            barrier.wait(timeout=20)
            return current
        def retry(event_id):
            with session() as db:
                try:
                    return operations.retry_failed(db, event_id, expected_attempts=3, request_id=request_id)
                except ValueError as exc:
                    return {'event_id': event_id, 'error': str(exc)}
        with patch.object(operations, '_current', side_effect=rendezvous):
            with ThreadPoolExecutor(max_workers=len(event_ids)) as pool:
                return list(pool.map(retry, event_ids))

    try:
        migrate('v74c01')
        with engine.begin() as db:
            db.execute(text("INSERT INTO cases(case_number,description,operational_area_id) "
                            "VALUES ('V75-PRE-UPGRADE','升级前合成原文，不得改变',1)"))
            db.execute(text("INSERT INTO users(id,username,display_name,password_hash,role,is_active) "
                            "VALUES (1,'v75-synthetic-admin','合成管理员','not-a-login','admin',true)"))
        migrate('v75r01')
        with session() as db:
            assert db.scalar(text('SELECT version_num FROM alembic_version')) == 'v75r01'
            assert db.scalar(text("SELECT udt_name FROM information_schema.columns WHERE "
                                  "table_name='case_history_vector_reuse' AND column_name='embedding'")) == 'vector'
            index = db.scalar(text("SELECT indexdef FROM pg_indexes WHERE indexname='uq_derived_retry_request'"))
            assert 'UNIQUE INDEX' in index and 'derived_task.explicit_retry' in index and 'WHERE' in index
            cases = [Case(case_number=f'V75-PG-{number}', description='重复合成片段。重复合成片段。',
                          operational_area_id=1) for number in range(3)]
            db.add_all(cases)
            db.flush()
            for case in cases:
                CaseSourceService.capture_change(db, case)
            db.commit()
            case_ids = [case.id for case in cases]
        with Session(engine, autoflush=False) as db:
            result = CaseHistoryIndexService.reconcile_batch(db)
            db.commit()
            assert result['failed_cases'] == 0 and result['reused_vectors'] >= 5
            assert encoder.calls.count('重复合成片段。') == 1
            cached = db.scalar(select(CaseHistoryVectorReuse).where(
                CaseHistoryVectorReuse.text_sha256 == text_hash('重复合成片段。')))
            assert cached.dimension == 2 and list(cached.embedding) == [1., 0.]
            assert db.scalar(text('SELECT min(vector_dims(embedding)) FROM case_history_vector_reuse')) == 2
            assert {row.case_id for row in db.scalars(select(CaseHistoryFragment).where(
                CaseHistoryFragment.quote == '重复合成片段。'))} == set(case_ids)
            calls = len(encoder.calls)
            CaseHistoryIndexService.reconcile_batch(db)
            db.commit()
            assert len(encoder.calls) == calls

        with session() as db:
            event_ids = [seed_failed(db, db.get(Case, case_id)) for case_id in case_ids]
            assert db.query(CaseAnalysisProfile).count() == 0
        same_request = str(uuid4())
        same = concurrent_retry([event_ids[0]] * 3, same_request)
        assert all(item.get('accepted') for item in same)
        assert sum(not item['replayed'] for item in same) == 1
        with session() as db:
            assert db.query(AuditLog).filter_by(action=operations.ACTION, request_id=same_request).count() == 1
            assert db.get(OutboxEvent, event_ids[0]).status == 'retry'
            assert db.get(OutboxEvent, event_ids[0]).attempts == 3

        shared_request = str(uuid4())
        cross = concurrent_retry(event_ids[1:], shared_request)
        winners = [item['event_id'] for item in cross if item.get('accepted')]
        losers = [item['event_id'] for item in cross if item.get('error') == 'derived_retry_request_conflict']
        assert len(winners) == len(losers) == 1
        with session() as db:
            receipt = db.query(AuditLog).filter_by(action=operations.ACTION, request_id=shared_request).one()
            assert receipt.detail == {'event_id': winners[0], 'expected_attempts': 3}
            assert db.get(OutboxEvent, winners[0]).status == 'retry'
            loser = db.get(OutboxEvent, losers[0])
            assert loser.status == 'failed' and loser.error == 'history_embedding_failed'
            assert loser.attempts == 3 and loser.payload['ordinary_failures'] == 3  # Losing CAS rolled back.
            assert db.query(CaseAnalysisProfile).count() == 0 and len(encoder.calls) == calls
            # Other audit actions retain their existing non-unique semantics.
            db.add_all([AuditLog(user_id=1, action='unrelated.audit', request_id=shared_request) for _ in range(2)])
            db.commit()
            expected = {model.__tablename__: db.query(model).count() for model in
                        (Case, CaseRevision, OutboxEvent, AuditLog, CaseHistoryFragment, CaseHistoryVectorReuse)}

        with pytest.raises(RuntimeError, match='derived_retry_receipts_require_compatible_backup_before_downgrade'):
            migrate('v75h01', direction='downgrade')
        with engine.connect() as db:
            assert db.scalar(text('SELECT version_num FROM alembic_version')) == 'v75r01'
            assert db.scalar(text("SELECT COUNT(*) FROM audit_logs WHERE action='derived_task.explicit_retry'")) == 2
            assert any(item['name'] == 'uq_derived_retry_request' for item in inspect(db).get_indexes('audit_logs'))

        backup = subprocess.run(['docker', 'exec', container, 'pg_dump', '-U', username, '-d', names[0],
                                 '--no-owner', '--no-privileges'], capture_output=True, check=True, timeout=60)
        subprocess.run(['docker', 'exec', '-i', container, 'psql', '-U', username, '-d', names[1], '-v', 'ON_ERROR_STOP=1'],
                       input=backup.stdout, capture_output=True, check=True, timeout=60)
        with session(restored) as db:
            assert db.scalar(text('SELECT version_num FROM alembic_version')) == 'v75r01'
            for model in (Case, CaseRevision, OutboxEvent, AuditLog, CaseHistoryFragment, CaseHistoryVectorReuse):
                assert db.query(model).count() == expected[model.__tablename__]
            assert db.query(Case).filter_by(case_number='V75-PRE-UPGRADE').one().description == '升级前合成原文，不得改变'
            assert db.scalar(text('SELECT min(vector_dims(embedding)) FROM case_history_vector_reuse')) == 2
            replay = operations.retry_failed(db, event_ids[0], expected_attempts=3, request_id=same_request)
            assert replay['accepted'] and replay['replayed']
            with pytest.raises(ValueError, match='derived_retry_request_conflict'):
                operations.retry_failed(db, losers[0], expected_attempts=3, request_id=shared_request)
            assert db.query(AuditLog).filter_by(action=operations.ACTION).count() == 2

        migrate('v75r01', target_engine=fresh)
        migrate('v74c01', target_engine=fresh, direction='downgrade')
        migrate('v75r01', target_engine=fresh)
        with fresh.connect() as db:
            assert db.scalar(text('SELECT version_num FROM alembic_version')) == 'v75r01'
            assert db.scalar(text('SELECT COUNT(*) FROM case_history_vector_reuse')) == 0
            assert any(item['name'] == 'uq_derived_retry_request' for item in inspect(db).get_indexes('audit_logs'))
        print('Verified v7.5 PG: upgrade, native vectors/reuse, same/cross-event concurrency, '
              'losing CAS rollback, guarded downgrade, restore and empty round-trip.', flush=True)
    finally:
        for target in engines:
            target.dispose()
