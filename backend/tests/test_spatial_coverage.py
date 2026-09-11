from datetime import datetime, timezone

import pytest

from app.models.jurisdiction import JurisdictionAsset
from app.services.spatial_coverage_service import compare_coverage
from tests.test_case_search_page import search_db  # noqa: F401

AS_OF = datetime(2026, 9, 11, tzinfo=timezone.utc)


def inventory(db):
    rows = [JurisdictionAsset(name=name, asset_type=kind, operational_area_id=1,
        latitude=lat, longitude=124, geometry_type='point', coordinate_system='EPSG:4326',
        verified=True, status='active', attributes={
            'coverage_radius_m': 200, 'operational_status': 'online',
            'operational_status_valid_until': '2026-09-12T00:00:00+00:00'})
        for name, kind, lat in [('设备甲', 'camera', 47), ('设备乙', 'lighting', 47),
                                ('井甲', 'well', 47), ('井乙', 'well', 47.01)]]
    db.add_all(rows)
    db.commit()
    db.info['authorized_area_ids'] = (1,)
    return rows


def test_overlap_is_unique_and_removing_resources_changes_coverage(search_db):
    rows = inventory(search_db)
    result = compare_coverage(search_db, 1, as_of=AS_OF,
                              disabled_resource_ids=(rows[0].id, rows[1].id))
    assert result['baseline']['covered_count'] == 1
    assert result['baseline']['overlap_count'] == 1
    assert result['baseline']['outside_known_count'] == 1
    assert result['scenario']['covered_count'] == 0
    assert result['covered_count_change'] == -1
    assert result['road_accessibility']['state'] == 'not_calculated'
    assert result['execution_task_created'] is False
    assert rows[0].attributes['operational_status'] == 'online'


def test_movement_and_frozen_inputs_are_reproducible_without_asset_changes(search_db):
    rows = inventory(search_db)
    arguments = {'as_of': AS_OF, 'movements': {rows[1].id: (47.01, 124)}}
    result = compare_coverage(search_db, 1, **arguments)
    assert result['scenario']['covered_count'] == 2
    assert result['scenario']['overlap_count'] == 0
    assert compare_coverage(search_db, 1, **arguments)['input_digest'] == result['input_digest']
    search_db.refresh(rows[1])
    assert rows[1].latitude == 47
    rows[1].latitude = 48
    search_db.commit()
    assert compare_coverage(search_db, 1, **arguments)['input_digest'] != result['input_digest']
    assert result['input_snapshot']['resources'][1]['latitude'] == 47


@pytest.mark.parametrize('failure', ['radius', 'status', 'expiry', 'coordinates'])
def test_missing_conditions_do_not_become_definite_uncovered_targets(search_db, failure):
    rows = inventory(search_db)
    attributes = dict(rows[0].attributes)
    if failure == 'radius':
        attributes['coverage_radius_m'] = None
    elif failure == 'status':
        attributes['operational_status'] = 'unknown'
    elif failure == 'expiry':
        attributes['operational_status_valid_until'] = '2020-01-01T00:00:00+00:00'
    else:
        rows[0].coordinate_system = 'unknown'
    rows[0].attributes = attributes
    search_db.commit()
    result = compare_coverage(search_db, 1, as_of=AS_OF)
    assert result['baseline']['covered_count'] == 1
    assert result['baseline']['unknown_count'] == 1
    assert result['baseline']['outside_known_count'] == 0


def test_invalid_target_and_empty_inventory_remain_unknown(search_db):
    rows = inventory(search_db)
    rows[2].latitude = None
    search_db.delete(rows[0])
    search_db.delete(rows[1])
    search_db.commit()
    result = compare_coverage(search_db, 1, as_of=AS_OF)
    assert result['baseline']['unknown_count'] == 2
    assert result['baseline']['covered_count'] == 0


def test_scope_and_hypothetical_inputs_are_checked(search_db):
    rows = inventory(search_db)
    with pytest.raises(PermissionError):
        compare_coverage(search_db, 2, as_of=AS_OF)
    with pytest.raises(PermissionError):
        compare_coverage(search_db, 1, as_of=AS_OF, disabled_resource_ids=(9999,))
    with pytest.raises(ValueError):
        compare_coverage(search_db, 1, as_of=AS_OF, movements={rows[0].id: (float('nan'), 124)})
    with pytest.raises(ValueError):
        compare_coverage(search_db, 1, as_of=AS_OF.replace(tzinfo=None))
    del search_db.info['authorized_area_ids']
    with pytest.raises(PermissionError):
        compare_coverage(search_db, 1, as_of=AS_OF)


def test_http_default_scope_and_invalid_requests(search_db, monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import governance
    from app.database import get_db

    rows = inventory(search_db)
    monkeypatch.setattr(governance.settings, 'AUTH_REQUIRED', True)
    app = FastAPI()
    app.include_router(governance.router, prefix='/api')
    role = {'value': 'analyst'}

    @app.middleware('http')
    async def principal(request, call_next):
        if role['value']:
            request.state.principal = SimpleNamespace(role=role['value'])
        return await call_next(request)

    def database():
        yield search_db

    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        path = '/api/deployment-sandbox/spatial-compare'
        response = client.post(path, json={})
        assert response.status_code == 200
        assert response.json()['input_snapshot']['area_id'] == 1
        assert response.json()['baseline']['target_count'] == 2
        history_path = '/api/deployment-sandbox/spatial-comparisons/' + response.json()['id']
        assert response.json()['persisted'] is True
        assert client.get(history_path).json()['historical'] is True
        catalog = client.get('/api/deployment-sandbox/spatial-comparisons', params={'page_size': 1})
        assert catalog.status_code == 200 and catalog.json()['total'] == 1
        assert set(catalog.json()['items'][0]) == {'id', 'operational_area_id', 'created_at'}
        assert client.get('/api/deployment-sandbox/spatial-comparisons', params={'page': 2, 'page_size': 1}).json()['items'] == []
        assert client.get('/api/deployment-sandbox/spatial-comparisons', params={'page_size': 1000}).status_code == 422
        assert client.post(path, json={'operational_area_id': 2}).status_code == 404
        assert client.post(path, json={'disabled_resource_ids': [9999]}).status_code == 404
        assert client.post(path, json={'disabled_resource_ids': [True]}).status_code == 422
        assert client.post(path, json={'coverage_factor': 1}).status_code == 422
        movement = {'resource_id': rows[0].id, 'latitude': 47, 'longitude': 124}
        assert client.post(path, json={'movements': [movement, movement]}).status_code == 422
        search_db.info['authorized_area_ids'] = ()
        assert client.get('/api/deployment-sandbox/spatial-comparisons').json()['total'] == 0
        search_db.info['authorized_area_ids'] = (1,)
        role['value'] = 'viewer'
        assert client.post(path, json={}).status_code == 403
        role['value'] = None
        assert client.post(path, json={}).status_code == 401
        assert client.get(history_path).status_code == 401


def test_inventory_limit_is_explicit_not_truncated(search_db, monkeypatch):
    import app.services.spatial_coverage_service as coverage
    inventory(search_db)
    monkeypatch.setattr(coverage, 'MAX_TARGETS', 1)
    with pytest.raises(ValueError, match='coverage_background_batch_required'):
        compare_coverage(search_db, 1, as_of=AS_OF)


def test_saved_history_is_frozen_and_rechecks_resources(search_db):
    from app.services.spatial_coverage_service import save_comparison, read_comparison
    rows = inventory(search_db)
    saved = save_comparison(search_db, compare_coverage(search_db, 1, as_of=AS_OF), created_by=None)
    assert saved['persisted'] is True
    first = read_comparison(search_db, saved['id'], now=AS_OF)
    assert first['freshness'] == 'unchanged_inputs'
    late = read_comparison(search_db, saved['id'], now=datetime(2026, 9, 13, tzinfo=timezone.utc))
    assert late['freshness'] == 'conditions_expired'
    rows[0].latitude = 48
    search_db.commit()
    changed = read_comparison(search_db, saved['id'], now=AS_OF)
    assert changed['freshness'] == 'source_changed'
    assert changed['input_snapshot']['resources'][0]['latitude'] == 47
    rows[0].operational_area_id = 2
    search_db.commit()
    with pytest.raises(PermissionError):
        read_comparison(search_db, saved['id'], now=AS_OF)


def test_history_integrity_and_area_revocation(search_db):
    from app.models.governance import SpatialCoverageComparison
    from app.services.spatial_coverage_service import save_comparison, read_comparison
    inventory(search_db)
    saved = save_comparison(search_db, compare_coverage(search_db, 1, as_of=AS_OF), created_by=None)
    search_db.info['authorized_area_ids'] = ()
    with pytest.raises(PermissionError):
        read_comparison(search_db, saved['id'], now=AS_OF)
    search_db.info['authorized_area_ids'] = (1,)
    row = search_db.query(SpatialCoverageComparison).filter_by(id=saved['id']).one()
    row.checksum = 'invalid'
    search_db.commit()
    with pytest.raises(ValueError, match='integrity'):
        read_comparison(search_db, saved['id'], now=AS_OF)


def test_saved_map_version_does_not_follow_later_publication(search_db, monkeypatch):
    from types import SimpleNamespace
    from app.services.spatial_coverage_service import OfflineMapService, save_comparison, read_comparison
    inventory(search_db)
    current = {'id': 'map-before'}
    monkeypatch.setattr(OfflineMapService, 'current_snapshot',
                        lambda db, area_id: SimpleNamespace(id=current['id']) if current['id'] else None)
    saved = save_comparison(search_db, compare_coverage(search_db, 1, as_of=AS_OF), created_by=None)
    assert saved['input_snapshot']['map_snapshot_id'] == 'map-before'
    current['id'] = 'map-after'
    historical = read_comparison(search_db, saved['id'], now=AS_OF)
    assert historical['freshness'] == 'source_changed'
    assert historical['input_snapshot']['map_snapshot_id'] == 'map-before'
    current['id'] = None
    assert compare_coverage(search_db, 1, as_of=AS_OF)['input_snapshot']['map_snapshot_id'] is None


def test_read_checks_frozen_inputs_without_repeating_spatial_calculation(search_db, monkeypatch):
    import app.services.spatial_coverage_service as service
    rows = inventory(search_db)
    saved = service.save_comparison(search_db, compare_coverage(search_db, 1, as_of=AS_OF), created_by=None)
    def forbidden(*args, **kwargs):
        raise AssertionError('history must not recalculate geometry or distances')
    monkeypatch.setattr(service, 'coverage_area', forbidden)
    monkeypatch.setattr(service, 'haversine_km', forbidden)
    assert service.read_comparison(search_db, saved['id'], now=AS_OF)['freshness'] == 'unchanged_inputs'
    rows[0].latitude = 48
    search_db.commit()
    result = service.read_comparison(search_db, saved['id'], now=AS_OF)
    assert result['freshness'] == 'source_changed'
    assert result['baseline'] == saved['baseline']


def test_unmodified_scenario_measures_area_once_without_sharing_mutable_results(search_db, monkeypatch):
    import app.services.spatial_coverage_service as service
    inventory(search_db)
    calls = []
    def measured(*args, **kwargs):
        calls.append(1)
        return {'state': 'test', 'information_gaps': []}
    monkeypatch.setattr(service, 'coverage_area', measured)
    result = compare_coverage(search_db, 1, as_of=AS_OF)
    assert len(calls) == 1
    assert result['baseline'] == result['scenario']
    result['scenario']['area_coverage']['information_gaps'].append('scenario-only')
    assert result['baseline']['area_coverage']['information_gaps'] == []
