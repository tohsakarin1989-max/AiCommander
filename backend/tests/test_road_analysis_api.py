from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api import road_analysis as api
from app.database import get_db
from app.services.vehicle_router import RoadCalculationError
from test_map_foundation import db_session  # noqa: F401
from test_internal_road_import import source  # noqa: F401


def client(db, role='admin'):
    app = FastAPI()
    if role:
        @app.middleware('http')
        async def principal(request: Request, call_next):
            request.state.principal = SimpleNamespace(user_id=1, role=role)
            return await call_next(request)
    app.include_router(api.router, prefix='/api/road-analysis')
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def payload():
    return {'vehicle': {'kind': 'auto'}, 'analysis_at': '2026-09-11T00:00:00Z',
            'start': {'longitude': 125., 'latitude': 46.},
            'end': {'longitude': 125.01, 'latitude': 46.}}


def test_reference_route_uses_server_root_and_automatic_authorized_selection(db_session, monkeypatch):
    def calculate(db, **kwargs):
        assert db.info['principal_user_id'] == 1
        assert 'network_id' not in kwargs
        assert kwargs['artifact_root'].name == 'road-graphs'
        assert kwargs['vehicle'].source == 'explicit_reference_assumption'
        return {'distance_m': 1050., 'network_id': 'synthetic', 'limitations': ['reference_only']}
    monkeypatch.setattr(api.calculations, 'calculate_reference_route', calculate)
    response = client(db_session).post('/api/road-analysis/routes', json=payload())
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['distance_m'] == 1050.


def test_read_only_area_permission_is_not_lost_for_query_post(db_session, source, monkeypatch):
    from app.models.map_foundation import UserAreaScope
    from app.models.user import User
    db_session.get(User, 1).role = 'analyst'
    db_session.add(UserAreaScope(user_id=1, operational_area_id=1, access_level='read'))
    db_session.commit()
    def calculate(db, **kwargs):
        assert db.info['authorized_area_ids'] == (1,)
        return {'distance_m': 1., 'fixture_only': True}
    monkeypatch.setattr(api.calculations, 'calculate_reference_route', calculate)
    assert client(db_session, 'analyst').post('/api/road-analysis/routes', json=payload()).status_code == 200


@pytest.mark.parametrize('field,value', [('ignore_restrictions', True), ('artifact_root', '/private'),
    ('network_id', 'other-group'), ('url', 'https://outside.invalid')])
def test_private_engine_and_filesystem_parameters_rejected(db_session, field, value):
    response = client(db_session).post('/api/road-analysis/routes', json={**payload(), field: value})
    assert response.status_code == 422


def test_authentication_and_reference_provenance(db_session):
    url = '/api/road-analysis/routes'
    assert client(db_session, None).post(url, json=payload()).status_code == 401
    assert client(db_session, 'viewer').post(url, json=payload()).status_code == 403
    data = payload()
    data['vehicle']['source'] = 'case_record'
    assert client(db_session).post(url, json=data).status_code == 422
    data = payload()
    data['analysis_at'] = '2026-09-11T00:00:00'
    assert client(db_session).post(url, json=data).status_code == 422


@pytest.mark.parametrize('code,status', [('road_calculation_timeout', 504),
    ('road_location_connection_unverified', 422), ('road_engine_calculation_failed', 503),
    ('private_path_do_not_expose', 503)])
def test_errors_do_not_fabricate_unreachable_or_leak_native_text(db_session, monkeypatch, code, status):
    def failure(*args, **kwargs):
        raise RoadCalculationError(code)
    monkeypatch.setattr(api.calculations, 'calculate_reference_route', failure)
    response = client(db_session).post('/api/road-analysis/routes', json=payload())
    assert response.status_code == status
    assert 'distance_m' not in response.json()
    assert 'private_path' not in response.text
    assert response.headers['cache-control'] == 'no-store'


def test_matrix_bounds_and_shared_read_service(db_session, monkeypatch):
    point = payload()['start']
    data = {'vehicle': {'kind': 'auto'}, 'sources': [point], 'targets': [point]}
    def matrix(db, **kwargs):
        assert len(kwargs['sources']) == len(kwargs['targets']) == 1
        return {'cells': [{'status': 'calculated', 'distance_m': 0}]}
    monkeypatch.setattr(api.calculations, 'calculate_distance_matrix', matrix)
    api_client = client(db_session)
    url = '/api/road-analysis/distance-matrices'
    assert api_client.post(url, json=data).status_code == 200
    assert api_client.post(url, json={**data, 'targets': [point] * 11}).status_code == 422
    assert api_client.post(url, json={**data, 'sources': []}).status_code == 422


def test_busy_and_unconfigured_graph_fail_without_blocking_request(db_session):
    api_client = client(db_session)
    assert api._slots.acquire(blocking=False)
    assert api._slots.acquire(blocking=False)
    try:
        response = api_client.post('/api/road-analysis/routes', json=payload())
        assert response.status_code == 429 and response.headers['retry-after'] == '5'
    finally:
        api._slots.release()
        api._slots.release()
    # Real database service, no ready networks or memberships configured.
    response = api_client.post('/api/road-analysis/routes', json=payload())
    assert response.status_code in (403, 503)
    assert 'distance_m' not in response.json()


@pytest.mark.parametrize('suffix,body', [('/comparison', None), ('/routes/1', {
    'network_id': '00000000-0000-0000-0000-000000000001', 'graph_sha256': 'a' * 64,
    'content_sha256': 'b' * 64, 'analysis_at': '2026-09-11T00:00:00Z'})])
def test_missing_frozen_case_is_sanitized_before_vehicle_selection(db_session, suffix, body):
    response = client(db_session).post('/api/road-analysis/case-results/missing' + suffix, json=body)
    assert response.status_code == 404
    assert response.headers['cache-control'] == 'no-store'
    assert 'distance_m' not in response.json()
