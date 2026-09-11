from types import SimpleNamespace

import pytest

from app.services import coverage_road_comparison as service
from app.services.road_access_policy import VehicleAssumption
from app.services.spatial_coverage_service import compare_coverage, save_comparison
from app.services.vehicle_router import RoadCalculationError
from tests.test_spatial_coverage import inventory, AS_OF
from tests.test_case_search_page import search_db  # noqa: F401

VEHICLE = VehicleAssumption(kind='auto', source='explicit_reference_assumption')


def saved(db, origin=True, disabled=False, moved=False):
    rows = inventory(db)
    if origin:
        rows[0].asset_type = 'checkpoint'
        rows[0].attributes = {**rows[0].attributes, 'road_reference_origin': True}
        db.commit()
    result = compare_coverage(db, 1, as_of=AS_OF,
        disabled_resource_ids=(rows[0].id,) if disabled else (),
        movements={rows[0].id: (47.01, 124)} if moved else {})
    return save_comparison(db, result, created_by=None), rows


def test_no_registered_origin_does_not_route_from_camera(search_db, tmp_path, monkeypatch):
    result, _ = saved(search_db, origin=False)
    def unexpected(*args, **kwargs):
        pytest.fail('must not invent a vehicle origin')
    monkeypatch.setattr(service, 'select_network', unexpected)
    value = service.compare_coverage_roads(search_db, result['id'], at=AS_OF, vehicle=VEHICLE,
        distance_budget_m=3000, artifact_root=tmp_path)
    assert value['state'] == 'information_missing'
    assert value['matrix_batches'] == []


@pytest.mark.parametrize('mode', ['normal', 'disabled', 'moved', 'failure', 'network_changed', 'source_changed'])
def test_road_budget_uses_real_matrix_contract_and_failures_never_become_distance(
    search_db, tmp_path, monkeypatch, mode,
):
    result, rows = saved(search_db, disabled=mode == 'disabled', moved=mode == 'moved')
    binding = SimpleNamespace(network_id='test', graph_sha256='a' * 64, policy_revision=1)
    monkeypatch.setattr(service, 'select_network', lambda *args, **kwargs: binding)
    checks = []
    monkeypatch.setattr(service, 'recheck_network', lambda *args, **kwargs: checks.append(True))

    def matrix(db, **kwargs):
        assert kwargs['network_id'] == 'test'
        assert kwargs['vehicle'] == VEHICLE
        assert 0 < kwargs['timeout_seconds'] <= 120
        assert len(kwargs['sources']) == 1
        if mode == 'failure':
            raise RoadCalculationError('road_engine_calculation_failed')
        if mode == 'source_changed':
            rows[0].latitude = 48
            db.commit()
        return {'graph_sha256': 'changed' if mode == 'network_changed' else binding.graph_sha256,
                'policy_revision': 1,
                'cells': [{'source_index': 0, 'target_index': index, 'status': 'calculated',
                           'distance_m': distance, 'reference_time_seconds': 100}
                          for index, distance in enumerate([2000, 4000])]}

    monkeypatch.setattr(service, 'calculate_distance_matrix', matrix)
    arguments = dict(at=AS_OF, vehicle=VEHICLE, distance_budget_m=3000, artifact_root=tmp_path)
    if mode in {'failure', 'network_changed', 'source_changed'}:
        with pytest.raises((RoadCalculationError, ValueError)):
            service.compare_coverage_roads(search_db, result['id'], **arguments)
        return
    value = service.compare_coverage_roads(search_db, result['id'], **arguments)
    assert value['state'] == 'calculated_reference' and checks
    assert value['targets'][0]['baseline_origin_ids_within_budget'] == [rows[0].id]
    assert value['targets'][1]['baseline_origin_ids_within_budget'] == []
    assert value['targets'][0]['scenario_origin_ids_within_budget'] == ([] if mode in {'disabled', 'moved'} else [rows[0].id])
    assert value['targets'][0]['scenario_connection_unknown'] is (mode == 'moved')
