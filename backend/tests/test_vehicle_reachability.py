import os
from pathlib import Path

import pytest

from app.services.road_access_policy import VehicleAssumption
from app.services.road_worker_process import run_distance_reachability_process
from app.services.vehicle_router import RoadCalculationError, RoadLocation
from test_road_reachability_geometry import expansion
from test_vehicle_router import router  # noqa: F401


ORIGIN = RoadLocation(longitude=124.9995, latitude=46.)
VEHICLE = VehicleAssumption(kind='auto', source='explicit_reference_assumption')


def contour_response():
    return {'type': 'FeatureCollection', 'features': [{'properties': {'metric': 'distance', 'contour': .5},
             'geometry': {'type': 'LineString', 'coordinates': [[125., 46.], [125.001, 46.]]}}]}


@pytest.mark.parametrize('native_contract', [None, 'completed-v1'])
def test_reachability_uses_same_restricted_request_and_directed_correlations(router, monkeypatch, native_contract):
    calls = []

    def locate(payload):
        calls.append(payload)
        return [{'edges': [{'distance': 0., 'edge_info': {'way_id': 1},
                            'edge_id': {'value': identifier}, 'percent_along': .5}
                           for identifier in (1, 2)]}]

    def expand(payload):
        calls.append(payload)
        result = expansion()
        if native_contract:
            result['properties']['aicommander_expansion_contract'] = native_contract
        return result

    def isochrone(payload):
        calls.append(payload)
        return contour_response()

    monkeypatch.setattr(router._actor, 'locate', locate)
    monkeypatch.setattr(router._actor, 'expansion', expand, raising=False)
    monkeypatch.setattr(router._actor, 'isochrone', isochrone, raising=False)
    result = router.distance_reachability(ORIGIN, VEHICLE, 500)
    assert result['schema_version'] == 'vehicle-distance-reachability-4.2.0-2'
    assert result['search_objective'] == 'shortest_road_distance'
    assert result['correlations'] == [{'way_ids': [1], 'maximum_distance_m': 0.}]
    assert max(f['properties']['end_distance_m'] for f in result['roads']['features']) == 500
    assert len(calls) == 3
    assert calls[2]['contours'] == [{'distance': .5}]
    assert calls[2]['skip_opposites'] is False
    assert calls[2]['generalize'] == 0
    assert calls[1]['polygons'] is False
    assert result['status'] == 'partial_reference'
    assert result['native_completion_contract'] == native_contract
    assert result['completion'] == {'budget_calculation': 'completed', 'road_expansion': 'unverified'}
    assert all(p['costing_options'] == {'auto': {'shortest': True}} for p in calls)
    assert all(p['locations'][0]['search_cutoff'] == 30 for p in calls)


@pytest.mark.parametrize('budget', [True, 0, -1, float('nan'), 50001, '500'])
def test_invalid_budget_never_invokes_native_engine(router, budget):
    with pytest.raises(ValueError, match='road_reachability_budget_invalid'):
        router.distance_reachability(ORIGIN, VEHICLE, budget)
    assert router._actor.calls == []


def test_missing_directed_seed_is_not_replaced_by_nearest_geometry(router):
    with pytest.raises(RoadCalculationError, match='road_location_connection_unverified'):
        router.distance_reachability(ORIGIN, VEHICLE, 500)


@pytest.mark.parametrize('fault', ['native_error', 'empty', 'wrong_budget', 'missing_geometry'])
def test_failed_budget_calculation_cannot_become_successful_expansion(router, monkeypatch, fault):
    monkeypatch.setattr(router._actor, 'locate', lambda payload: [{'edges': [
        {'distance': 0., 'edge_info': {'way_id': 1}, 'edge_id': {'value': 1}, 'percent_along': .5}]}])

    def isochrone(payload):
        if fault == 'native_error':
            raise RuntimeError('native private error')
        result = contour_response()
        if fault == 'empty':
            result['features'] = []
        elif fault == 'wrong_budget':
            result['features'][0]['properties']['contour'] = 5
        else:
            result['features'][0]['geometry']['coordinates'] = []
        return result

    def forbidden(payload):
        pytest.fail('failed budget calculation must stop before expansion')

    monkeypatch.setattr(router._actor, 'isochrone', isochrone, raising=False)
    monkeypatch.setattr(router._actor, 'expansion', forbidden, raising=False)
    with pytest.raises(RoadCalculationError):
        router.distance_reachability(ORIGIN, VEHICLE, 500)


@pytest.mark.skipif(not os.environ.get('AIC_CLOSED_TEST_GRAPH'), reason='requires built closed-road fixture')
def test_real_isolated_distance_reachability():
    from app.services.road_graph_artifact import graph_inventory_sha256
    tiles = Path(os.environ['AIC_CLOSED_TEST_GRAPH'])
    assert graph_inventory_sha256(tiles) == '75d6ec33a3f0efbd8ac6630ef6ba781bfdfadbf6e92fd8729737662715896d6b'
    result = run_distance_reachability_process(tiles, ORIGIN, VEHICLE, 500, timeout_seconds=30)
    assert result['schema_version'] == 'vehicle-distance-reachability-4.2.0-2'
    assert len(result['roads']['features']) == 3
    assert max(f['properties']['end_distance_m'] for f in result['roads']['features']) == 500
    assert result['roads']['features'][-1]['geometry']['coordinates'][-1][1] > 46.


@pytest.mark.skipif(not os.environ.get('AIC_REAL_ROAD_GRAPH'), reason='requires frozen public graph')
def test_public_graph_boundaries_remain_on_actual_roads():
    from app.services.road_graph_artifact import graph_inventory_sha256
    from app.services.vehicle_router import VehicleRouter
    tiles = Path(os.environ['AIC_REAL_ROAD_GRAPH'])
    assert graph_inventory_sha256(tiles) == '3e0ff861f57a1d1ee0d7248be4a1df6e39657861e77bb0d7df669d2ed2d98ae4'
    router = VehicleRouter(tiles)
    origin = RoadLocation(longitude=125.1852727, latitude=46.54446175)
    result = router.distance_reachability(origin, VEHICLE, 500)
    # Shortest-distance search includes five branches hidden by default costing
    # on this SHA-frozen public graph; geometry assertions below still apply.
    assert len(result['roads']['features']) == 88
    assert result['search_objective'] == 'shortest_road_distance'
    for feature in result['roads']['features']:
        lon, lat = feature['geometry']['coordinates'][-1]
        # Tight matching catches the native default 10m simplification, which
        # previously left three interpolated boundary points off-road.
        trip = router._actor.route({'costing': 'auto', 'units': 'kilometers',
            'costing_options': {'auto': {'shortest': True}}, 'locations': [
            {'lon': origin.longitude, 'lat': origin.latitude, 'radius': 1, 'search_cutoff': 3,
             'minimum_reachability': 0},
            {'lon': lon, 'lat': lat, 'radius': 1, 'search_cutoff': 3, 'minimum_reachability': 0}]})
        assert trip['trip']['summary']['length'] * 1000 <= 505
