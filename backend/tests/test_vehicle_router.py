import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.road_access_policy import VehicleAssumption
from app.services.vehicle_router import RoadCalculationError, RoadLocation, VehicleRouter


class SyntheticActor:
    def __init__(self):
        self.calls = []
        self.distance = 2
        self.way = 1

    def locate(self, payload):
        self.calls.append(payload)
        return [{'edges': [{'distance': self.distance, 'edge_info': {'way_id': 1}}]}]

    def route(self, payload):
        self.calls.append(payload)
        return {'trip': {'status': 0, 'units': 'kilometers',
                         'summary': {'length': 1.2, 'time': 100}, 'legs': [{'shape': '??AC'}]}}

    def trace_attributes(self, payload):
        self.calls.append(payload)
        return {'edges': [{'way_id': self.way}]}


@pytest.fixture
def router():
    result = VehicleRouter.__new__(VehicleRouter)
    result._actor = SyntheticActor()
    return result


def run(router):
    return router.route(RoadLocation(longitude=125., latitude=46.),
                        RoadLocation(longitude=125.1, latitude=46.1),
                        VehicleAssumption(kind='auto', source='explicit_reference_assumption'))


def test_units_trace_and_private_request_contract(router):
    result = run(router)
    assert result['distance_m'] == 1200
    assert result['way_ids'] == [1]
    assert result['reference_time_seconds'] == 100
    assert len(router._actor.calls) == 4
    assert router._actor.calls[2]['alternates'] == 1
    assert result['alternatives'] == []
    assert all(item['costing_options'] == {'auto': {}} for item in router._actor.calls)
    with pytest.raises(ValidationError):
        RoadLocation(longitude=125., latitude=46., ignore_restrictions=True)


@pytest.mark.parametrize('kind', ['distinct', 'duplicate', 'wrong_endpoint', 'invalid_measure'])
def test_alternative_has_independent_measure_and_endpoint_validation(router, monkeypatch, kind):
    original = router._actor.route
    def routes(payload):
        result = original(payload)
        result['alternates'] = [{'trip': {'status': 0, 'units': 'kilometers',
            'summary': {'length': -1 if kind == 'invalid_measure' else 1.5, 'time': 120},
            'legs': [{'shape': '??AC' if kind == 'duplicate' else '??EG'}]}}]
        return result
    def trace(payload):
        if payload['encoded_polyline'] == '??AC':
            return {'edges': [{'way_id': 1}]}
        return {'edges': [{'way_id': 999 if kind == 'wrong_endpoint' else 1}, {'way_id': 2}, {'way_id': 1}]}
    monkeypatch.setattr(router._actor, 'route', routes)
    monkeypatch.setattr(router._actor, 'trace_attributes', trace)
    if kind in ('wrong_endpoint', 'invalid_measure'):
        with pytest.raises(RoadCalculationError):
            run(router)
    else:
        result = run(router)
        assert result['distance_m'] == 1200
        assert len(result['alternatives']) == (1 if kind == 'distinct' else 0)
        if kind == 'distinct':
            assert result['alternatives'][0]['distance_m'] == 1500


@pytest.mark.parametrize('distance', [31, float('nan'), -1, True])
def test_far_or_invalid_snap_cannot_become_route(router, distance):
    router._actor.distance = distance
    with pytest.raises(RoadCalculationError, match='connection_unverified'):
        run(router)
    assert len(router._actor.calls) == 1


def test_route_must_end_on_correlated_roads(router):
    router._actor.way = 999
    with pytest.raises(RoadCalculationError, match='route_connection_unverified'):
        run(router)


def test_engine_failure_never_returns_straight_line(router, monkeypatch):
    def unavailable(payload):
        raise RuntimeError('sensitive native message')
    monkeypatch.setattr(router._actor, 'route', unavailable)
    with pytest.raises(RoadCalculationError, match='^road_engine_calculation_failed$'):
        run(router)


def test_truck_without_dimensions_is_not_silently_defaulted(router):
    point = RoadLocation(longitude=125., latitude=46.)
    with pytest.raises(RoadCalculationError, match='vehicle_dimensions_missing'):
        router.route(point, point, VehicleAssumption(kind='truck', source='case_record'))
    assert not router._actor.calls


@pytest.mark.skipif(not os.environ.get('AIC_REAL_ROAD_GRAPH'), reason='requires frozen real Valhalla graph and optional engine')
def test_real_frozen_graph_forbidden_left_turn():
    # Public source fixture, not operational case/production coordinates.
    from app.services.road_graph_artifact import graph_inventory_sha256
    tiles = Path(os.environ['AIC_REAL_ROAD_GRAPH'])
    assert graph_inventory_sha256(tiles) == '3e0ff861f57a1d1ee0d7248be4a1df6e39657861e77bb0d7df669d2ed2d98ae4'
    router = VehicleRouter(tiles)
    result = router.route(
        RoadLocation(longitude=125.1852727, latitude=46.54446175),
        RoadLocation(longitude=125.18509545, latitude=46.5444392),
        VehicleAssumption(kind='auto', source='explicit_reference_assumption'))
    ways = result['way_ids']
    assert ways[0] == 1550481791 and ways[-1] == 1550481790
    assert (1550481791, 1550481790) not in list(zip(ways, ways[1:]))
    assert result['distance_m'] > 100
