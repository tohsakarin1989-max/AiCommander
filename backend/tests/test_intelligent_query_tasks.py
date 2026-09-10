from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

from app.database import bind_principal_scope
from app.models.user import User
from app.models.map_foundation import UserAreaScope
from app.models.agent_run import AgentRun, AgentEvent
from app.services import intelligent_query_tasks as tasks
from tests.test_case_search_page import search_db, add_case  # noqa: F401


@pytest.fixture
def query_db(search_db):
    for uid in (1, 2):
        search_db.add(User(id=uid, username=f'query-{uid}', display_name='test',
            password_hash='not-a-login', role='analyst', is_active=True))
    search_db.flush()
    search_db.add_all([UserAreaScope(user_id=uid, operational_area_id=1, access_level='read')
                       for uid in (1, 2)])
    search_db.commit()
    bind_principal_scope(search_db, SimpleNamespace(user_id=1, role='analyst'), method='GET')
    return search_db


def test_create_read_cancel_persist_and_do_not_modify_business(query_db):
    case = add_case(query_db, 'ORIGINAL')
    query_db.commit()
    run = tasks.create_query(query_db, '有多少案件？')
    query_db.expire_all()
    assert tasks.read_query(query_db, run['id'])['status'] == 'queued'
    assert tasks.cancel_query(query_db, run['id'])['status'] == 'cancelled'
    assert tasks.cancel_query(query_db, run['id'])['status'] == 'cancelled'
    assert query_db.query(AgentEvent).filter_by(run_id=run['id']).count() == 2
    assert case.case_number == 'ORIGINAL'


def test_other_owner_cannot_read_or_cancel(query_db):
    run = tasks.create_query(query_db, '统计')
    query_db.info['principal_user_id'] = 2
    for action in (tasks.read_query, tasks.cancel_query):
        with pytest.raises(ValueError, match='query_not_found'):
            action(query_db, run['id'])


def test_permission_change_hides_old_result_but_allows_cancel(query_db):
    run = tasks.create_query(query_db, '统计')
    query_db.query(UserAreaScope).filter_by(user_id=1).delete()
    query_db.commit()
    with pytest.raises(PermissionError, match='query_scope_changed'):
        tasks.read_query(query_db, run['id'])
    assert tasks.cancel_query(query_db, run['id'])['status'] == 'cancelled'


def test_moved_case_invalidates_old_scope_membership(query_db):
    case = add_case(query_db, 'MOVING')
    query_db.commit()
    run = tasks.create_query(query_db, '统计')
    case.operational_area_id = 2
    query_db.commit()
    with pytest.raises(PermissionError, match='query_scope_changed'):
        tasks.read_query(query_db, run['id'])


def test_cancel_wins_over_late_completion(query_db):
    run = tasks.create_query(query_db, '统计')
    attempt = tasks.claim_query(query_db, run['id'])
    assert attempt is not None
    assert tasks.claim_query(query_db, run['id']) is None
    tasks.cancel_query(query_db, run['id'])
    assert tasks.finish_query(query_db, run['id'], attempt, {
        'status': 'completed', 'cards': [], 'trace': [], 'error_code': None}) is False
    assert query_db.get(AgentRun, run['id']).status == 'cancelled'


def test_completion_keeps_cards_and_trace_in_database(query_db):
    run = tasks.create_query(query_db, '统计')
    attempt = tasks.claim_query(query_db, run['id'])
    assert tasks.finish_query(query_db, run['id'], attempt, {
        'status': 'completed', 'cards': [{'data': {'count': 0}}],
        'trace': [{'step': 1, 'tool': 'count_cases'}], 'error_code': None})
    query_db.expire_all()
    read = tasks.read_query(query_db, run['id'])
    assert read['result']['cards'][0]['data']['count'] == 0
    assert read['result']['trace'][0]['tool'] == 'count_cases'
    assert read['result_kind'] == 'historical_query_snapshot'


def test_expired_attempt_cannot_finish(query_db):
    run = tasks.create_query(query_db, '统计')
    attempt = tasks.claim_query(query_db, run['id'])
    row = query_db.get(AgentRun, run['id'])
    row.started_at = datetime.now(timezone.utc) - timedelta(minutes=3)
    query_db.commit()
    assert not tasks.finish_query(query_db, run['id'], attempt, {
        'status': 'completed', 'cards': [], 'trace': [], 'error_code': None})
    assert tasks.expire_query(query_db, run['id'])['status'] == 'expired'


@pytest.mark.asyncio
async def test_persisted_task_runs_actual_tools_and_reads_back(query_db):
    add_case(query_db, 'ONE')
    query_db.commit()
    run = tasks.create_query(query_db, '统计')
    steps = iter(['{"action":"call","tool":"count_cases","arguments":{}}',
                  '{"action":"finish","reason":"completed"}'])
    class Model:
        async def ainvoke(self, prompt):
            return SimpleNamespace(content=next(steps))
    result = await tasks.execute_query(query_db, run['id'], model=Model())
    assert result['status'] == 'completed'
    assert tasks.read_query(query_db, run['id'])['result']['cards'][0]['data']['count'] == 1


@pytest.mark.asyncio
async def test_cancel_during_model_wait_is_durable(query_db):
    run = tasks.create_query(query_db, '统计')
    class Model:
        async def ainvoke(self, prompt):
            tasks.cancel_query(query_db, run['id'])
            return SimpleNamespace(content='{"action":"call","tool":"count_cases","arguments":{}}')
    result = await tasks.execute_query(query_db, run['id'], model=Model())
    assert result['status'] == 'cancelled'
    assert tasks.read_query(query_db, run['id'])['result'] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize('disable_user', [False, True])
async def test_revocation_during_model_wait_terminates_without_result(query_db, disable_user):
    run = tasks.create_query(query_db, '统计')
    class Model:
        async def ainvoke(self, prompt):
            if disable_user:
                query_db.get(User, 1).is_active = False
            else:
                query_db.query(UserAreaScope).filter_by(user_id=1).delete()
            query_db.commit()
            return SimpleNamespace(content='{"action":"call","tool":"count_cases","arguments":{}}')
    result = await tasks.execute_query(query_db, run['id'], model=Model())
    assert result['status'] == 'cancelled'
    assert query_db.get(AgentRun, run['id']).result_summary == {}


def test_legacy_agent_endpoints_cannot_bypass_query_owner_boundary(query_db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.agent_runs import router
    from app.config import settings
    from app.database import get_db
    monkeypatch.setattr(settings, 'ENABLE_AGENT_LAB', True)
    monkeypatch.setattr(settings, 'AGENT_MODE', 'shadow')
    monkeypatch.setattr(settings, 'AUTH_REQUIRED', False)
    run = tasks.create_query(query_db, 'PRIVATE QUESTION')
    query_db.info['principal_user_id'] = 2
    app = FastAPI()
    app.include_router(router, prefix='/api/agent-runs')
    def session():
        yield query_db
    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        assert client.get('/api/agent-runs').json() == []
        for suffix in ('', '/events'):
            assert client.get(f"/api/agent-runs/{run['id']}{suffix}").status_code == 404
        for suffix in ('/cancel', '/replay'):
            assert client.post(f"/api/agent-runs/{run['id']}{suffix}", json={}).status_code == 404
