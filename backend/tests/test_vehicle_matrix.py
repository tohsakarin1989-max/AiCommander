import os
from pathlib import Path

import pytest

from app.services.road_access_policy import VehicleAssumption
from app.services.road_worker_process import run_matrix_process, run_route_process
from app.services.vehicle_router import RoadCalculationError, RoadLocation
from test_vehicle_router import router  # noqa: F401


POINT = RoadLocation(longitude=125., latitude=46.)
VEHICLE = VehicleAssumption(kind='auto', source='explicit_reference_assumption')


@pytest.mark.parametrize('change', ['none', 'null', 'half_null', 'far', 'order', 'shape', 'nan'])
def test_matrix_response_validation(router, monkeypatch, change):
    cell = {'from_index': 0, 'to_index': 0, 'distance': .12, 'time': 12,
            'begin_lat': 46., 'begin_lon': 125., 'end_lat': 46., 'end_lon': 125.}
    rows = [[cell]]
    if change == 'null':
        cell.update(distance=None, time=None)
    elif change == 'half_null':
        cell['distance'] = None
    elif change == 'far':
        cell['end_lat'] = 47.
    elif change == 'order':
        cell['from_index'] = 1
    elif change == 'shape':
        rows = []
    elif change == 'nan':
        cell['distance'] = float('nan')
    monkeypatch.setattr(router._actor, 'matrix', lambda payload: {
        'units': 'kilometers', 'sources_to_targets': rows}, raising=False)
    if change in ('none', 'null'):
        result = router.matrix([POINT], [POINT], VEHICLE)
        assert result['cells'][0]['distance_m'] == (120 if change == 'none' else None)
        assert result['cells'][0]['status'] == ('calculated' if change == 'none' else 'no_path_found')
    else:
        with pytest.raises(RoadCalculationError, match='road_engine_response_invalid'):
            router.matrix([POINT], [POINT], VEHICLE)


def test_matrix_budget_checked_before_engine(router):
    with pytest.raises(ValueError, match='matrix_size'):
        router.matrix([POINT] * 11, [POINT], VEHICLE)
    assert not router._actor.calls


@pytest.mark.skipif(not os.environ.get('AIC_REAL_ROAD_GRAPH'), reason='requires frozen real graph and engine')
def test_real_isolated_matrix_keeps_direction_and_matches_route():
    from app.services.road_graph_artifact import graph_inventory_sha256
    tiles = Path(os.environ['AIC_REAL_ROAD_GRAPH'])
    assert graph_inventory_sha256(tiles) == '3e0ff861f57a1d1ee0d7248be4a1df6e39657861e77bb0d7df669d2ed2d98ae4'
    points = [RoadLocation(longitude=125.1852727, latitude=46.54446175),
              RoadLocation(longitude=125.18509545, latitude=46.5444392)]
    matrix = run_matrix_process(tiles, points, points, VEHICLE, timeout_seconds=30)
    distances = [cell['distance_m'] for cell in matrix['cells']]
    assert distances[0] == distances[3] == 0
    assert distances[2] > distances[1] > 100
    route = run_route_process(tiles, *points, VEHICLE, timeout_seconds=30)
    # Native matrix and route serialize length at slightly different precision.
    assert abs(distances[1] - route['distance_m']) <= 5
