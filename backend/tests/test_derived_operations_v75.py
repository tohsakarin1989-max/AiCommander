"""Read-only admin queues and explicit failed-derived retries, no generic replay."""
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event

from app.api.derived_operations import router
from app.database import get_db
from app.models.case_pipeline import OutboxEvent
from app.models.user import User, AuditLog
from app.services.case_pipeline_service import CasePipelineService
from app.services import derived_operations as operations
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_case_search_page import add_case


def seed(db):
    db.get(User, 1).role = 'admin'
    case = add_case(db, 'ADMIN-DERIVED', description='不能改写的合成事实')
    row = CasePipelineService.enqueue_case_change(db, case)
    row.status, row.attempts = 'failed', 3
    db.commit()
    return case, row


def client(db, user_id=1):
    app = FastAPI()
    @app.middleware('http')
    async def identity(request, call_next):
        if user_id:
            request.state.principal = SimpleNamespace(user_id=user_id, role='admin')
        return await call_next(request)
    def session():
        yield db
    app.dependency_overrides[get_db] = session
    app.include_router(router, prefix='/api/admin/derived-tasks')
    return TestClient(app)


def test_admin_listing_reads_only_and_filters_before_pagination(query_db):
    case, row = seed(query_db)
    query_db.add(OutboxEvent(id='approved-action', event_type='agent.mutation.approved',
        aggregate_type='case', aggregate_id=str(case.id), payload={'secret': '原始提示词'},
        idempotency_key='approved-action', status='failed'))
    query_db.commit()
    statements = []
    def observe(_c, _cu, sql, _p, _ctx, _many):
        statements.append(sql)
    event.listen(query_db.bind, 'before_cursor_execute', observe)
    try:
        response = client(query_db).get('/api/admin/derived-tasks?page_size=1&status=failed')
    finally:
        event.remove(query_db.bind, 'before_cursor_execute', observe)
    assert response.status_code == 200
    data = response.json()
    assert data['total'] == data['counts']['failed'] == 1
    assert data['items'][0]['id'] == row.id and data['items'][0]['retryable']
    assert '原始提示词' not in response.text and '不能改写的合成事实' not in response.text
    assert not any(sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for sql in statements)
    assert client(query_db, 2).get('/api/admin/derived-tasks').status_code == 403
    assert client(query_db, None).get('/api/admin/derived-tasks').status_code == 401


def test_explicit_retry_receipt_and_audit_commit_together(query_db):
    case, row = seed(query_db)
    request = {'request_id': str(uuid4()), 'expected_attempts': 3}
    path = f'/api/admin/derived-tasks/{row.id}/retry'
    first = client(query_db).post(path, json=request)
    assert first.status_code == 202 and not first.json()['replayed']
    again = client(query_db).post(path, json=request)
    assert again.status_code == 202 and again.json()['replayed']
    query_db.refresh(row)
    assert row.status == 'retry' and row.attempts == 3
    assert query_db.query(AuditLog).filter_by(action=operations.ACTION).count() == 1
    assert case.description == '不能改写的合成事实'
    assert client(query_db).post(path, json={**request, 'expected_attempts': 4}).status_code == 409
    assert client(query_db).post(path, json={**request, 'command': 'run-anything'}).status_code == 422


@pytest.mark.parametrize('state', ['completed', 'cancelled', 'processing', 'pending'])
def test_never_revives_completed_cancelled_or_active_work(query_db, state):
    _, row = seed(query_db)
    row.status = state
    query_db.commit()
    with pytest.raises(ValueError, match='state_changed'):
        operations.retry_failed(query_db, row.id, expected_attempts=3, request_id=str(uuid4()))
    query_db.refresh(row)
    assert row.status == state and query_db.query(AuditLog).count() == 0


def test_source_change_and_unknown_types_are_not_retryable(query_db):
    case, row = seed(query_db)
    case.description = '后来明确更正的事实'
    query_db.commit()
    assert not operations.directory(query_db)['items'][0]['retryable']
    with pytest.raises(ValueError, match='source_outdated'):
        operations.retry_failed(query_db, row.id, expected_attempts=3, request_id=str(uuid4()))
    row.event_type = 'agent.mutation.approved'
    query_db.commit()
    with pytest.raises(ValueError, match='type_not_allowed'):
        operations.retry_failed(query_db, row.id, expected_attempts=3, request_id=str(uuid4()))


def test_retry_is_not_a_new_inline_analysis(query_db):
    from app.models.case_pipeline import CaseAnalysisProfile
    _, row = seed(query_db)
    assert query_db.query(CaseAnalysisProfile).count() == 0
    operations.retry_failed(query_db, row.id, expected_attempts=3, request_id=str(uuid4()))
    assert query_db.query(CaseAnalysisProfile).count() == 0
    assert query_db.query(OutboxEvent).filter_by(event_type='case.analysis.requested').count() == 1


def test_history_debt_requires_current_complete_stamp_and_does_not_encode(query_db, monkeypatch):
    from app.services.case_history_index_debt import current_input_stamp
    from app.services.local_embedding_service import LocalEmbeddingService
    case, _ = seed(query_db)
    def forbidden(*args):
        pytest.fail('metadata/retry must not perform embedding inference')
    monkeypatch.setattr(LocalEmbeddingService, 'encode', forbidden)
    stamp = current_input_stamp(query_db, case)
    debt = OutboxEvent(id=str(uuid4()), event_type='case.history.index.retry',
        aggregate_type='case', aggregate_id=str(case.id), payload=stamp,
        idempotency_key=f'history-index-retry:{case.id}', status='failed', attempts=3)
    query_db.add(debt)
    query_db.commit()
    assert next(row for row in operations.directory(query_db)['items'] if row['id'] == debt.id)['retryable']
    request_id = str(uuid4())
    assert operations.retry_failed(query_db, debt.id, expected_attempts=3, request_id=request_id)['accepted']
    query_db.refresh(debt)
    debt.status = 'failed'
    debt.attempts = 4
    case.description = '索引来源后来变化'
    query_db.commit()
    with pytest.raises(ValueError, match='source_outdated'):
        operations.retry_failed(query_db, debt.id, expected_attempts=4, request_id=str(uuid4()))
