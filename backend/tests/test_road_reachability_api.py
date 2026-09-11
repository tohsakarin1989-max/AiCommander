import pytest
from sqlalchemy import update

from app.api import road_analysis as api
from app.models.user import User
from app.services.vehicle_router import RoadCalculationError
from test_map_foundation import db_session  # noqa: F401
from test_road_analysis_api import client


def payload(metric):
    return {'metric': metric, 'vehicle': {'kind': 'auto'},
            'origin': {'longitude': 125., 'latitude': 46.},
            **({'distance_m': 500.} if metric == 'distance' else {'seconds': 60.})}


@pytest.mark.parametrize('metric', ['distance', 'time'])
def test_analyst_budgeted_roads_use_shared_authorized_calculation(db_session, monkeypatch, metric):
    db_session.execute(update(User).where(User.id == 1).values(role='analyst'))
    db_session.commit()
    def calculate(db, **kwargs):
        assert db.info['principal_user_id'] == 1
        assert 'network_id' not in kwargs and kwargs['cancel_event'] is not None
        return {'status': 'partial_reference', 'native_completion_contract': 'completed-v1',
                'roads': {'type': 'FeatureCollection', 'features': []}}
    monkeypatch.setattr(api.calculations, f'calculate_{metric}_reachability', calculate)
    response = client(db_session, 'analyst').post('/api/road-analysis/reachable-roads', json=payload(metric))
    assert response.status_code == 200, response.text
    assert response.json()['interpretation'] == 'budgeted_road_segments_only'
    assert response.json()['status'] == 'partial_reference'
    assert '不等于不可达' in response.json()['boundary']
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('marker', [None, 'unknown'])
def test_ordinary_roads_reject_unproven_native_completion(db_session, monkeypatch, marker):
    monkeypatch.setattr(api.calculations, 'calculate_distance_reachability', lambda *a, **kw: {
        'native_completion_contract': marker, 'roads': {'features': []}})
    response = client(db_session).post('/api/road-analysis/reachable-roads', json=payload('distance'))
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'road_engine_completion_required'
    assert 'roads' not in response.json()


def test_ordinary_roads_recheck_revoked_role(db_session, monkeypatch):
    def calculate(db, **kwargs):
        db.execute(update(User).where(User.id == 1).values(role='viewer'))
        db.commit()
        return {'native_completion_contract': 'completed-v1', 'roads': {'features': []}}
    monkeypatch.setattr(api.calculations, 'calculate_distance_reachability', calculate)
    response = client(db_session).post('/api/road-analysis/reachable-roads', json=payload('distance'))
    assert response.status_code == 403 and 'roads' not in response.json()


@pytest.mark.parametrize('role,status', [(None, 401), ('viewer', 403)])
def test_ordinary_roads_require_analysis_permission(db_session, role, status):
    assert client(db_session, role).post('/api/road-analysis/reachable-roads', json=payload('distance')).status_code == status


def test_ordinary_roads_cannot_override_hard_restrictions(db_session):
    response = client(db_session).post('/api/road-analysis/reachable-roads', json={
        **payload('distance'), 'ignore_restrictions': True})
    assert response.status_code == 422


def test_case_budget_http_uses_server_vehicle_and_rejects_client_origin(db_session, monkeypatch):
    from app.services import case_road_comparison
    from app.services.road_access_policy import VehicleAssumption
    from datetime import datetime, timezone
    frozen = api.ServerCaseCalculation(analysis_at=datetime.now(timezone.utc),
        vehicle=VehicleAssumption(kind='truck', source='case_record', height_m=3., weight_t=12.))
    monkeypatch.setattr(api, '_case_calculation', lambda *a: frozen)
    def calculate(db, **kwargs):
        assert kwargs['vehicle'] == frozen.vehicle
        assert kwargs['result_id'] == 'result' and kwargs['budget'] == 500.
        assert 'origin' not in kwargs
        return {'schema_version': 'case-reachable-roads-4.2.0-1', 'reachability': None,
                'information_gaps': ['缺少冻结坐标']}
    monkeypatch.setattr(case_road_comparison, 'reachable_result_roads', calculate)
    body = {'metric': 'distance', 'distance_m': 500., 'analysis_at': frozen.analysis_at.isoformat(),
        'network_id': '12345678-1234-1234-1234-123456789abc', 'graph_sha256': 'b' * 64,
        'content_sha256': 'a' * 64}
    url = '/api/road-analysis/case-results/result/reachable-roads'
    assert client(db_session).post(url, json=body).status_code == 200
    for forbidden in ({'origin': {'longitude': 0, 'latitude': 0}}, {'vehicle': {'kind': 'auto'}}):
        assert client(db_session).post(url, json={**body, **forbidden}).status_code == 422


@pytest.mark.parametrize('metric', ['time', 'distance'])
def test_admin_preview_selects_authorized_graph_and_preserves_partial_status(db_session, monkeypatch, metric):
    def calculation(db, **kwargs):
        assert db.info['principal_user_id'] == 1
        assert 'network_id' not in kwargs and kwargs['artifact_root'].name == 'road-graphs'
        assert kwargs['cancel_event'] is not None
        assert kwargs['seconds' if metric == 'time' else 'distance_m'] == (60 if metric == 'time' else 500)
        return {'status': 'partial_reference', 'roads': {'type': 'FeatureCollection', 'features': []},
                'completion': {'road_expansion': 'unverified'}}
    monkeypatch.setattr(api.calculations, f'calculate_{metric}_reachability', calculation)
    response = client(db_session).post('/api/road-analysis/reachability-previews', json=payload(metric))
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'partial_reference'
    assert response.headers['cache-control'] == 'no-store'
    assert not db_session.new and not db_session.dirty


@pytest.mark.parametrize('role,status', [(None, 401), ('viewer', 403), ('analyst', 403)])
def test_unreleased_capability_is_not_available_to_ordinary_users(db_session, role, status):
    assert client(db_session, role).post('/api/road-analysis/reachability-previews', json=payload('time')).status_code == status


def test_old_admin_session_does_not_override_current_role(db_session):
    db_session.execute(update(User).where(User.id == 1).values(role='analyst'))
    db_session.commit()
    assert client(db_session).post('/api/road-analysis/reachability-previews', json=payload('time')).status_code == 403


def test_admin_revoked_during_calculation_does_not_receive_preview(db_session, monkeypatch):
    def calculation(db, **kwargs):
        db.execute(update(User).where(User.id == 1).values(role='analyst'))
        db.commit()
        return {'status': 'partial_reference', 'roads': {'features': []}}
    monkeypatch.setattr(api.calculations, 'calculate_time_reachability', calculation)
    response = client(db_session).post('/api/road-analysis/reachability-previews', json=payload('time'))
    assert response.status_code == 403 and 'roads' not in response.json()


@pytest.mark.parametrize('extra', [{'seconds': True}, {'seconds': '60'}, {'seconds': 7201},
    {'distance_m': 500}, {'network_id': 'other-group'}, {'ignore_restrictions': True},
    {'artifact_root': '/private'}, {'metric': 'unknown'}])
def test_budget_and_private_parameters_are_rejected(db_session, extra):
    response = client(db_session).post('/api/road-analysis/reachability-previews', json={**payload('time'), **extra})
    assert response.status_code == 422


@pytest.mark.parametrize('error,status', [('road_calculation_timeout', 504),
    ('road_calculation_cancelled', 409), ('road_calculation_capacity_exceeded', 422),
    ('sensitive-native-detail', 503)])
def test_failed_calculation_never_returns_empty_success(db_session, monkeypatch, error, status):
    def fail(*args, **kwargs):
        raise RoadCalculationError(error)
    monkeypatch.setattr(api.calculations, 'calculate_time_reachability', fail)
    response = client(db_session).post('/api/road-analysis/reachability-previews', json=payload('time'))
    assert response.status_code == status
    assert 'roads' not in response.json() and 'sensitive-native-detail' not in response.text
