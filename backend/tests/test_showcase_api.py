from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.showcase import router
from app.config import settings
from app.database import get_db
from app.models.case import Case
from app.agent_runtime.service import AgentRunService
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401


def client_for(db, uid=1, role='analyst'):
    app = FastAPI()
    @app.middleware('http')
    async def principal(request, call_next):
        if uid is not None:
            request.state.principal = SimpleNamespace(user_id=uid, role=role)
        return await call_next(request)
    def session():
        yield db
    app.dependency_overrides[get_db] = session
    app.include_router(router, prefix='/api/showcase')
    return TestClient(app)


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(settings, 'ENABLE_SHOWCASE', True)


def test_live_archive_idempotent_retry_and_business_isolation(query_db):
    with client_for(query_db) as client:
        body = {'scenario': 'normal', 'request_id': '12345678-1234-4234-9234-123456789012'}
        response = client.post('/api/showcase/runs', json=body)
        assert response.status_code == 201
        assert response.json()['view_kind'] == 'live_result'
        assert response.json()['result']['analysis']['hypotheses']
        assert query_db.query(Case).count() == 0
        from app.services.agent_observability_service import AgentObservabilityService
        assert AgentObservabilityService.build_overview(query_db)['summary']['runs_total'] == 0
        archived = client.get(response.headers['location'])
        assert archived.json()['view_kind'] == 'historical_replay'
        assert archived.headers['cache-control'] == 'no-store'
        assert client.post('/api/showcase/runs', json=body).status_code == 200
        assert len(client.get('/api/showcase/runs').json()['items']) == 1
        with pytest.raises(ValueError):
            AgentRunService.get_run(query_db, body['request_id'])
    with client_for(query_db, uid=2) as other:
        assert other.get(response.headers['location']).status_code == 404


def test_guards_and_rejects_business_inputs(query_db, monkeypatch):
    with client_for(query_db) as client:
        assert client.post('/api/showcase/runs', json={'scenario': 'normal', 'case_id': 1}).status_code == 422
        monkeypatch.setattr(settings, 'ENABLE_SHOWCASE', False)
        assert client.get('/api/showcase/runs').status_code == 404
    monkeypatch.setattr(settings, 'ENABLE_SHOWCASE', True)
    with client_for(query_db, uid=None) as anonymous:
        assert anonymous.get('/api/showcase/runs').status_code == 401


def test_failure_is_recorded_without_internal_details(query_db, monkeypatch):
    from app.api import showcase
    monkeypatch.setattr(showcase, 'execute_scenario', lambda _: (_ for _ in ()).throw(RuntimeError('secret-path')))
    with client_for(query_db) as client:
        response = client.post('/api/showcase/runs', json={'scenario': 'normal',
            'request_id': '22345678-1234-4234-9234-123456789012'})
        assert response.status_code == 201
        assert response.json()['status'] == 'failed'
        assert 'secret-path' not in response.text


def test_interrupted_archive_expires_and_late_completion_cannot_restore_it(query_db, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.models.agent_run import AgentRun
    from app.api import showcase

    def interrupted(_):
        row = query_db.query(AgentRun).filter_by(task_type='showcase').one()
        row.started_at = datetime.now(timezone.utc) - timedelta(seconds=121)
        query_db.commit()
        return {'late': 'must not appear'}

    monkeypatch.setattr(showcase, 'execute_scenario', interrupted)
    with client_for(query_db) as client:
        body = {'scenario': 'normal', 'request_id': '32345678-1234-4234-9234-123456789012'}
        created = client.post('/api/showcase/runs', json=body)
        assert created.json()['status'] == 'expired'
        assert created.json()['result'] == {}
        assert client.post('/api/showcase/runs', json=body).json()['status'] == 'expired'


def test_current_role_rate_limit_and_request_conflict(query_db, monkeypatch):
    from uuid import uuid4
    from app.models.user import User
    from app.api import showcase
    monkeypatch.setattr(showcase, 'execute_scenario', lambda _: {'synthetic': True})
    with client_for(query_db) as client:
        body = {'scenario': 'normal', 'request_id': str(uuid4())}
        assert client.post('/api/showcase/runs', json=body).status_code == 201
        assert client.post('/api/showcase/runs', json={**body, 'scenario': 'missing_location'}).status_code == 409
        for _ in range(2):
            assert client.post('/api/showcase/runs', json={**body, 'request_id': str(uuid4())}).status_code == 201
        assert client.post('/api/showcase/runs', json={**body, 'request_id': str(uuid4())}).status_code == 429
        query_db.get(User, 1).role = 'viewer'
        query_db.commit()
        assert client.get('/api/showcase/runs').status_code == 403
