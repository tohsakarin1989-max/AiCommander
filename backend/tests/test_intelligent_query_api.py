from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.intelligent_queries import router
from app.config import settings
from app.database import get_db
from app.models.agent_run import AgentRun
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
    app.include_router(router, prefix='/api/intelligent-queries')
    return TestClient(app)


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(settings, 'ENABLE_AGENT_LAB', True)
    monkeypatch.setattr(settings, 'AGENT_MODE', 'shadow')


def test_create_read_cancel_without_broker_or_model(query_db):
    with client_for(query_db) as client:
        created = client.post('/api/intelligent-queries', json={'query': '统计案件'})
        assert created.status_code == 201
        assert created.headers['cache-control'] == 'no-store'
        url = created.headers['location']
        assert client.get(url).json()['status'] == 'queued'
        assert client.post(url + '/cancel').json()['status'] == 'cancelled'
        assert client.get(url).json()['status'] == 'cancelled'


def test_owner_and_authentication_boundary(query_db):
    with client_for(query_db) as owner:
        url = owner.post('/api/intelligent-queries', json={'query': 'PRIVATE'}).headers['location']
    with client_for(query_db, uid=2) as other:
        assert other.get(url).status_code == 404
        assert other.post(url + '/cancel').status_code == 404
    with client_for(query_db, uid=None) as anonymous:
        assert anonymous.get(url).status_code == 401
    with client_for(query_db, role='viewer') as viewer:
        assert viewer.post('/api/intelligent-queries', json={'query': '统计'}).status_code == 403


def test_disabled_and_invalid_requests_rejected(query_db, monkeypatch):
    with client_for(query_db) as client:
        for body in ({'query': ''}, {'query': '  '}, {'query': '统计', 'sql': 'SELECT 1'}):
            assert client.post('/api/intelligent-queries', json=body).status_code == 422
        monkeypatch.setattr(settings, 'ENABLE_AGENT_LAB', False)
        assert client.post('/api/intelligent-queries', json={'query': '统计'}).status_code == 404


def test_pending_capacity_is_bounded(query_db):
    with client_for(query_db) as client:
        for _ in range(4):
            assert client.post('/api/intelligent-queries', json={'query': '统计'}).status_code == 201
        response = client.post('/api/intelligent-queries', json={'query': '统计'})
        assert response.status_code == 429
        assert query_db.query(AgentRun).count() == 4


def test_followup_api_rejects_unfinished_and_accepts_owned_snapshot(query_db):
    from app.services import intelligent_query_tasks as tasks
    with client_for(query_db) as client:
        parent = client.post('/api/intelligent-queries', json={'query': '统计'}).json()
        body = {'query': '继续', 'parent_query_id': parent['id']}
        assert client.post('/api/intelligent-queries', json=body).status_code == 422
        attempt = tasks.claim_query(query_db, parent['id'])
        tasks.finish_query(query_db, parent['id'], attempt,
            {'status': 'completed', 'cards': [{'data': {'count': 0}}], 'trace': []})
        response = client.post('/api/intelligent-queries', json=body)
        assert response.status_code == 201
        assert response.json()['followup_context']['parent_query_id'] == parent['id']
        assert client.post('/api/intelligent-queries', json={**body, 'context': {}}).status_code == 422


def test_real_auth_middleware_login_and_cookie_origin_boundary():
    from tests.test_auth_security import _build_client, _bootstrap_admin
    client, factory = _build_client()
    client.app.include_router(router, prefix='/api/intelligent-queries')
    with client:
        assert client.post('/api/intelligent-queries', json={'query': '统计'}).status_code == 401
        assert _bootstrap_admin(client).status_code in (200, 201)
        created = client.post('/api/intelligent-queries', json={'query': '统计'})
        assert created.status_code == 201
        url = created.headers['location']
        assert client.get(url).status_code == 200
        assert client.post(url + '/cancel', headers={'Origin': 'https://untrusted.invalid'}).status_code == 403
        assert client.post(url + '/cancel').status_code == 200
    factory.kw['bind'].dispose()


def test_query_document_download_contract_and_owner_boundary(query_db):
    from app.services import intelligent_query_tasks as tasks
    with client_for(query_db) as client:
        task = client.post('/api/intelligent-queries', json={'query': '统计'}).json()
        url = f"/api/intelligent-queries/{task['id']}/document.docx"
        assert client.get(url).status_code == 422
        attempt = tasks.claim_query(query_db, task['id'])
        tasks.finish_query(query_db, task['id'], attempt, {'status': 'completed', 'cards': [
            {'tool': 'count_cases', 'state': 'ok', 'data': {'count': 0}}], 'trace': []})
        response = client.get(url)
        assert response.status_code == 200
        assert response.content.startswith(b'PK')
        assert response.headers['cache-control'] == 'no-store'
        assert len(response.headers['x-result-content-sha256']) == 64
    with client_for(query_db, uid=2) as other:
        assert other.get(url).status_code == 404


def test_pdf_runtime_failure_is_sanitized(query_db, monkeypatch):
    from app.api import intelligent_queries as api
    from app.services.case_result_export import CaseResultExportError
    def unavailable(*args):
        raise CaseResultExportError('internal_path_or_runtime_detail')
    monkeypatch.setattr(api, 'export_query_document', unavailable)
    with client_for(query_db) as client:
        task = client.post('/api/intelligent-queries', json={'query': '统计'}).json()
        response = client.get(f"/api/intelligent-queries/{task['id']}/document.pdf")
        assert response.status_code == 503
        assert 'internal_path' not in response.text
