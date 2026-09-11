from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import case_road_comparison as service
from app.services.road_access_policy import VehicleAssumption
from app.services.vehicle_router import RoadCalculationError


@pytest.mark.parametrize('metric', ['distance', 'time'])
@pytest.mark.parametrize('fault', ['none', 'missing_origin', 'old_engine', 'changed_source', 'changed_graph'])
def test_case_budget_uses_frozen_origin_vehicle_and_versions(context, monkeypatch, metric, fault):
    if fault == 'missing_origin':
        context['map']['case_marker'] = None
    monkeypatch.setattr(service, 'load_result_map_context', lambda *args: deepcopy(context))
    monkeypatch.setattr(service, 'resolve_network', lambda *args, **kwargs: SimpleNamespace(graph_sha256='b' * 64))
    monkeypatch.setattr(service.CaseResultService, 'read', lambda *args: {
        'content_sha256': ('c' if fault == 'changed_source' else 'a') * 64})
    calls = []
    vehicle = VehicleAssumption(kind='truck', source='case_record', height_m=3., weight_t=12.)
    def calculate(db, **kwargs):
        calls.append(kwargs)
        assert kwargs['origin'].longitude == 125. and kwargs['origin'].latitude == 46.
        assert kwargs['vehicle'] == vehicle and kwargs['network_id'] == 'fixed-network'
        assert kwargs['distance_m' if metric == 'distance' else 'seconds'] == 500.
        return {'graph_sha256': 'b' * 64,
                'native_completion_contract': None if fault == 'old_engine' else 'completed-v1'}
    monkeypatch.setattr(service, f'calculate_{metric}_reachability', calculate)
    kwargs = dict(result_id='result', network_id='fixed-network',
        graph_sha256=('c' if fault == 'changed_graph' else 'b') * 64, content_sha256='a' * 64,
        analysis_at=datetime.now(timezone.utc), vehicle=vehicle, artifact_root=None, metric=metric, budget=500.)
    if fault in ('changed_source', 'changed_graph', 'old_engine'):
        with pytest.raises(RoadCalculationError if fault == 'old_engine' else ValueError):
            service.reachable_result_roads(None, **kwargs)
    else:
        result = service.reachable_result_roads(None, **kwargs)
        assert result['map_snapshot_id'] == 'snapshot'
        if fault == 'missing_origin':
            assert result['reachability'] is None and result['information_gaps'] and not calls
        else:
            assert result['reachability']['native_completion_contract'] == 'completed-v1'
    if fault == 'changed_graph':
        assert not calls


@pytest.fixture
def context():
    return {'result_id': 'result', 'content_sha256': 'a' * 64,
        'map': {'case_marker': {'longitude': 125., 'latitude': 46.}, 'map_snapshot_id': 'snapshot',
                'candidates': [{'id': 'candidate', 'rank': 1, 'title': '候选设施',
                    'region': {'type': 'circle', 'center': [0, 0]},
                    'evidence_refs': ['map_asset:1@snapshot:snapshot']}]},
        'production': {'features': [{'geometry': {'type': 'Point', 'coordinates': [125.01, 46.]},
                                     'properties': {'asset_id': 1, 'name': '合成设施'}}]}}


def compare(context, monkeypatch):
    monkeypatch.setattr(service, 'load_result_map_context', lambda *args: deepcopy(context))
    monkeypatch.setattr(service.CaseResultService, 'read', lambda *args: {'content_sha256': context['content_sha256']})
    return service.compare_result_roads(None, result_id='result', analysis_at=datetime.now(timezone.utc),
        vehicle=VehicleAssumption(kind='auto', source='explicit_reference_assumption'), artifact_root=None)


def test_frozen_evidence_point_not_region_center_is_used(context, monkeypatch):
    def matrix(db, **kwargs):
        assert kwargs['targets'][0].longitude == 125.01
        assert kwargs['sources'][0].longitude == 125.
        return {'cells': [{'distance_m': 1000}]}
    monkeypatch.setattr(service, 'calculate_distance_matrix', matrix)
    result = compare(context, monkeypatch)
    assert result['targets'][0]['evidence_ref'] == 'map_asset:1@snapshot:snapshot'
    assert result['matrix']['cells'][0]['distance_m'] == 1000


@pytest.mark.parametrize('missing', ['origin', 'point', 'reference_version'])
def test_missing_or_wrong_version_inputs_do_not_trigger_guessed_route(context, monkeypatch, missing):
    if missing == 'origin':
        context['map']['case_marker'] = None
    elif missing == 'point':
        context['production']['features'][0]['geometry'] = {'type': 'LineString', 'coordinates': [[125., 46.], [126., 46.]]}
    else:
        context['map']['candidates'][0]['evidence_refs'] = ['map_asset:1@snapshot:other']
    def forbidden(*args, **kwargs):
        pytest.fail('must not call routing on inferred or mismatched points')
    monkeypatch.setattr(service, 'calculate_distance_matrix', forbidden)
    result = compare(context, monkeypatch)
    assert result['matrix'] is None and result['information_gaps']


@pytest.mark.parametrize('fault', ['none', 'other_asset', 'changed_graph', 'changed_result'])
def test_route_expansion_binds_result_target_and_comparison_network(context, monkeypatch, fault):
    monkeypatch.setattr(service, 'load_result_map_context', lambda *args: deepcopy(context))
    monkeypatch.setattr(service.CaseResultService, 'read', lambda *args: {'content_sha256': context['content_sha256']})
    monkeypatch.setattr(service, 'resolve_network', lambda *args, **kwargs: SimpleNamespace(graph_sha256='b' * 64))
    calls = []
    def route(db, **kwargs):
        calls.append(kwargs)
        assert kwargs['network_id'] == 'fixed-comparison-network'
        assert kwargs['end'].longitude == 125.01
        return {'graph_sha256': 'b' * 64, 'shape_polyline6': 'unit-fixture'}
    monkeypatch.setattr(service, 'calculate_reference_route', route)
    args = dict(result_id='result', asset_id=2 if fault == 'other_asset' else 1,
        network_id='fixed-comparison-network', graph_sha256=('c' if fault == 'changed_graph' else 'b') * 64,
        content_sha256=('d' if fault == 'changed_result' else 'a') * 64,
        analysis_at=datetime.now(timezone.utc), artifact_root=None,
        vehicle=VehicleAssumption(kind='auto', source='explicit_reference_assumption'))
    if fault == 'none':
        assert service.route_result_target(None, **args)['target']['asset_id'] == 1
        assert len(calls) == 1
    else:
        with pytest.raises(ValueError):
            service.route_result_target(None, **args)
        assert not calls
