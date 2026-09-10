import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api import map_package_imports
from app.config import settings
from app.database import get_db
from tests.test_map_package_imports import db_session, source


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setattr(settings, 'AUTH_REQUIRED', True)
    app = FastAPI()
    app.state.role = 'admin'

    @app.middleware('http')
    async def principal(request: Request, call_next):
        if app.state.role:
            request.state.principal = SimpleNamespace(role=app.state.role, user_id=None)
        return await call_next(request)

    def session():
        yield db_session

    app.dependency_overrides[get_db] = session
    app.include_router(map_package_imports.router, prefix='/api')
    with TestClient(app) as test_client:
        yield test_client


def test_http_resume_and_submit(client, source):
    directory, manifest = source
    created = client.post('/api/map-package-imports', content=json.dumps(manifest))
    assert created.status_code == 201
    url = created.headers['location']
    assert client.post(url + '/submit').status_code == 409
    for asset in manifest['assets']:
        for chunk in asset['chunks']:
            uploaded = client.put(url + '/chunks/' + chunk['file'], content=(directory / chunk['file']).read_bytes())
            assert uploaded.status_code == 200
    assert client.get(url).json()['missing_chunks'] == []
    assert client.post(url + '/submit').status_code == 202
    assert client.post(url + '/submit').json()['status'] == 'queued'


@pytest.mark.parametrize('role,code', [(None, 401), ('analyst', 403), ('viewer', 403)])
def test_only_admin_can_access_upload_metadata(client, source, role, code):
    _, manifest = source
    url = client.post('/api/map-package-imports', content=json.dumps(manifest)).headers['location']
    client.app.state.role = role
    assert client.get(url).status_code == code
    assert client.post('/api/map-package-imports', content=b'{}').status_code == code
    assert client.put(url + '/chunks/vector-0.part', content=b'x').status_code == code
    assert client.post(url + '/submit').status_code == code
    assert client.post(url + '/register').status_code == code


def test_register_requires_worker_result_and_returns_bundle(client, db_session, source, monkeypatch):
    from tests.test_map_package_registration import validated
    run_id = validated(db_session, source, monkeypatch)
    url = f'/api/map-package-imports/{run_id}'
    reply = client.post(url + '/register')
    assert reply.status_code == 200
    assert reply.json()['routing_available'] is False
    assert client.get(url).json()['registration']['public_bundle_id'] == reply.json()['public_bundle_id']
    assert reply.headers['cache-control'] == 'no-store'


def test_unvalidated_import_cannot_be_registered(client, source):
    _, manifest = source
    url = client.post('/api/map-package-imports', content=json.dumps(manifest)).headers['location']
    assert client.post(url + '/register').status_code == 409


def test_request_limits_and_invalid_manifest(client, monkeypatch):
    monkeypatch.setattr(map_package_imports, 'MAX_MANIFEST_BYTES', 10)
    assert client.post('/api/map-package-imports', content=b'x' * 11).status_code == 413
    assert client.post('/api/map-package-imports', content=b'{}').status_code == 422


def test_storage_failure_is_retryable_without_path_leak(client, source, monkeypatch):
    directory, manifest = source
    url = client.post('/api/map-package-imports', content=json.dumps(manifest)).headers['location']

    def fail(*args):
        raise OSError('/private/operator/path')

    monkeypatch.setattr(map_package_imports.service, '_chunk_directory', fail)
    reply = client.put(url + '/chunks/vector-0.part', content=(directory / 'vector-0.part').read_bytes())
    assert reply.status_code == 503
    assert '/private' not in reply.text
    assert client.get(url).json()['received_chunks'] == 0
