"""Explicit retry receipts serialize only their own request, using synthetic DBs."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.database import Base, bind_principal_scope
from app.models.case import Case
from app.models.case_pipeline import OutboxEvent
from app.models.map_foundation import OperationalArea
from app.models.user import AuditLog, User
from app.services import derived_operations as operations
from app.services.case_pipeline_service import CasePipelineService
from tests.test_case_search_page import add_case
from tests.test_result_material_migration_v65 import migrate


@pytest.fixture
def retry_database(tmp_path):
    # A real file gives the two worker Sessions independent SQLite connections.
    # It is unrelated to the configured application DB and contains no real data.
    engine = create_engine(
        f"sqlite:///{tmp_path / 'derived-retry.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    try:
        with sessions() as db:
            db.add(OperationalArea(id=1, code='synthetic-retry', name='合成重试验证区'))
            db.add(User(id=1, username='synthetic-retry-admin', display_name='合成管理员',
                        password_hash='not-a-login', role='admin', is_active=True))
            db.commit()
            bind_principal_scope(db, SimpleNamespace(user_id=1, role='admin'))
            identifiers = []
            for index in range(2):
                case = add_case(db, f'V75-RETRY-SYNTHETIC-{index}',
                                description=f'合成原始事实 {index}，重试不得改写')
                event = CasePipelineService.enqueue_case_change(db, case)
                event.status, event.attempts, event.error = 'failed', 3, 'synthetic-failure'
                event.payload = {**event.payload, 'ordinary_failures': 3}
                db.commit()
                identifiers.append(event.id)
            original_cases = db.execute(select(Case.__table__).order_by(Case.id)).all()
        yield sessions, identifiers, original_cases
    finally:
        engine.dispose()


def race_requests(sessions, identifiers, request_id, monkeypatch):
    """Force both real receipt reads to miss before either real CAS/commit."""
    barrier = Barrier(2)
    original_receipt = operations._receipt

    def simultaneous_receipt(db, *args):
        receipt = original_receipt(db, *args)
        if not db.info.get('retry_test_initial_receipt_read'):
            db.info['retry_test_initial_receipt_read'] = True
            assert receipt is None
            barrier.wait(timeout=10)
        return receipt

    monkeypatch.setattr(operations, '_receipt', simultaneous_receipt)

    def retry(event_id):
        with sessions() as db:
            bind_principal_scope(db, SimpleNamespace(user_id=1, role='admin'))
            return operations.retry_failed(
                db, event_id, expected_attempts=3, request_id=request_id,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(retry, event_id) for event_id in identifiers]
        # Exiting waits for both requests. No fake writes or receipt result stubs.
    return futures


def test_concurrent_same_event_replays_one_receipt_without_duplicate_retry(retry_database, monkeypatch):
    sessions, identifiers, original_cases = retry_database
    request_id = str(uuid4())
    futures = race_requests(sessions, [identifiers[0], identifiers[0]], request_id, monkeypatch)
    responses = [future.result() for future in futures]
    assert all(response['accepted'] for response in responses)
    assert {response['event_id'] for response in responses} == {identifiers[0]}
    assert sorted(response['replayed'] for response in responses) == [False, True]
    with sessions() as db:
        receipts = db.query(AuditLog).filter_by(action=operations.ACTION).all()
        assert len(receipts) == 1
        assert receipts[0].request_id == request_id
        assert receipts[0].detail == {'event_id': identifiers[0], 'expected_attempts': 3}
        event = db.get(OutboxEvent, identifiers[0])
        assert (event.status, event.attempts, event.error) == ('retry', 3, None)
        assert event.payload['ordinary_failures'] == 0
        assert db.get(OutboxEvent, identifiers[1]).status == 'failed'
        assert db.execute(select(Case.__table__).order_by(Case.id)).all() == original_cases


def test_concurrent_same_request_for_different_events_rolls_back_losing_cas(retry_database, monkeypatch):
    sessions, identifiers, original_cases = retry_database
    request_id = str(uuid4())
    futures = race_requests(sessions, identifiers, request_id, monkeypatch)
    accepted = [future.result() for future in futures if future.exception() is None]
    rejected = [future for future in futures if future.exception() is not None]
    assert len(accepted) == len(rejected) == 1
    assert accepted[0]['accepted'] and not accepted[0]['replayed']
    with pytest.raises(ValueError, match='^derived_retry_request_conflict$'):
        rejected[0].result()
    winner = accepted[0]['event_id']
    loser = next(identifier for identifier in identifiers if identifier != winner)
    with sessions() as db:
        receipts = db.query(AuditLog).filter_by(action=operations.ACTION).all()
        assert len(receipts) == 1
        assert receipts[0].request_id == request_id
        assert receipts[0].detail == {'event_id': winner, 'expected_attempts': 3}
        winning_event, losing_event = db.get(OutboxEvent, winner), db.get(OutboxEvent, loser)
        assert (winning_event.status, winning_event.attempts) == ('retry', 3)
        assert winning_event.payload['ordinary_failures'] == 0
        # Unique receipt failure must undo every field changed by the prior CAS.
        assert (losing_event.status, losing_event.attempts, losing_event.error) == (
            'failed', 3, 'synthetic-failure',
        )
        assert losing_event.payload['ordinary_failures'] == 3
        assert db.execute(select(Case.__table__).order_by(Case.id)).all() == original_cases


def test_retry_receipt_migration_preserves_other_audits_and_refuses_nonempty_downgrade(tmp_path):
    path = tmp_path / 'retry-receipt-migration.sqlite'
    url = f'sqlite:///{path}'
    before = migrate(url, 'upgrade', 'v75h01')
    assert before.returncode == 0, before.stderr
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO users(id,username,display_name,password_hash,role) "
                   "VALUES(1,'synthetic-receipt-admin','合成测试','not-a-login','admin')")
        db.execute("INSERT INTO cases(case_number,description) VALUES('V75-RECEIPT-MIGRATION','迁移前合成原文')")
        db.executemany("INSERT INTO audit_logs(user_id,action,request_id) VALUES(1,'unrelated.action',?)",
                       [('shared-request',), ('shared-request',)])
    # Empty receipt rollback remains reversible; existing unrelated audit keys
    # intentionally are not unique and must never be deleted or rewritten.
    for direction, revision in [('upgrade', 'v75r01'), ('downgrade', 'v75h01'), ('upgrade', 'v75r01')]:
        result = migrate(url, direction, revision)
        assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(path)) as db, db:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name='uq_derived_retry_request'").fetchone()[0]
        assert 'UNIQUE' in sql.upper() and "WHERE action = 'derived_task.explicit_retry'" in sql
        db.execute("INSERT INTO audit_logs(user_id,action,request_id,detail) VALUES(1,?,?,?)",
                   (operations.ACTION, 'shared-request', '{"event_id":"synthetic-event","expected_attempts":3}'))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO audit_logs(user_id,action,request_id) VALUES(1,?,?)",
                       (operations.ACTION, 'shared-request'))
        assert db.execute("SELECT COUNT(*) FROM audit_logs WHERE action='unrelated.action'").fetchone()[0] == 2
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    refused = migrate(url, 'downgrade', 'v75h01')
    assert refused.returncode != 0
    assert 'derived_retry_receipts_require_compatible_backup_before_downgrade' in refused.stderr
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == 'v75r01'
        assert db.execute("SELECT COUNT(*) FROM audit_logs WHERE action=?", (operations.ACTION,)).fetchone()[0] == 1
        assert db.execute('SELECT description FROM cases').fetchone()[0] == '迁移前合成原文'
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='uq_derived_retry_request'").fetchone() == (1,)
