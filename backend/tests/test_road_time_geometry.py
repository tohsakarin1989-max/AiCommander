import copy
import os
from pathlib import Path

import pytest

from app.services.road_time_geometry import clip_timed_path, refine_timed_path
from app.services.vehicle_router import RoadCalculationError, RoadLocation, VehicleRouter
from app.services.road_access_policy import VehicleAssumption


POINTS = [[125., 46.], [125.001, 46.], [125.002, 46.]]
EDGES = [
    {'id': 1, 'begin_shape_index': 0, 'end_shape_index': 1,
     'end_node': {'elapsed_time': 10., 'transition_time': 20.}},
    {'id': 2, 'begin_shape_index': 1, 'end_shape_index': 2,
     'end_node': {'elapsed_time': 40., 'transition_time': 0.}},
]


@pytest.mark.parametrize('budget,count,end_lon', [(5, 1, 125.0005), (10, 1, 125.001),
    (20, 1, 125.001), (30, 1, 125.001), (35, 2, 125.0015), (40, 2, 125.002), (60, 2, 125.002)])
def test_waiting_at_junction_does_not_move_vehicle_along_next_road(budget, count, end_lon):
    edges = copy.deepcopy(EDGES)
    result = clip_timed_path(POINTS, edges, budget)
    assert edges == EDGES
    assert len(result['features']) == count
    assert result['features'][-1]['geometry']['coordinates'][-1][0] == pytest.approx(end_lon)
    assert result['properties']['path_completed'] is (budget >= 40)


@pytest.mark.parametrize('fault', ['gap', 'missing_transition', 'negative', 'nan', 'reverse_time', 'truncated'])
def test_invalid_timing_never_produces_a_path(fault):
    edges = copy.deepcopy(EDGES)
    if fault == 'gap':
        edges[1]['begin_shape_index'] = 0
    elif fault == 'missing_transition':
        del edges[0]['end_node']['transition_time']
    elif fault == 'negative':
        edges[0]['end_node']['transition_time'] = -1
    elif fault == 'nan':
        edges[1]['end_node']['elapsed_time'] = float('nan')
    elif fault == 'reverse_time':
        edges[1]['end_node']['elapsed_time'] = 29
    else:
        edges.pop()
    with pytest.raises(RoadCalculationError):
        clip_timed_path(POINTS, edges, 35)


def test_partial_edge_native_cost_bias_refines_position_not_budget():
    calls = []

    def measured(candidate):
        arrival = candidate['features'][-1]['properties']['arrival_seconds']
        calls.append(arrival)
        return arrival + .238

    result = refine_timed_path(POINTS, EDGES, 35, measured)
    assert calls == pytest.approx([35, 34.757])
    assert result['properties']['time_budget_seconds'] == 35
    assert result['properties']['boundary_verified_seconds'] <= 35
    assert result['properties']['boundary_refinement_steps'] == 1
    assert result['features'][-1]['geometry']['coordinates'][-1][0] < 125.0015


def test_published_boundary_uses_the_actual_native_costed_coordinate():
    endpoint = [125.001499, 46.]
    result = refine_timed_path(POINTS, EDGES, 35,
        lambda candidate: {'seconds': 34.998, 'endpoint': endpoint})
    assert result['features'][-1]['geometry']['coordinates'][-1] == endpoint
    assert result['properties']['time_budget_seconds'] == 35
    assert result['properties']['boundary_verified_seconds'] == 34.998


def test_unresolved_terminal_sliver_is_explicit_and_keeps_last_verified_node():
    tiny_tail = [POINTS[0], POINTS[1], [125.001005, 46.]]
    result = refine_timed_path(tiny_tail, EDGES, 35, lambda candidate: {
        'seconds': 10., 'endpoint': POINTS[1], 'remove_terminal_sliver': True})
    assert len(result['features']) == 1
    assert result['properties']['boundary_resolution_limited_m'] == 1
    assert result['properties']['boundary_verified_seconds'] == 10
    assert result['properties']['time_budget_seconds'] == 35


@pytest.mark.parametrize('value', [float('nan'), -1, True, 999999])
def test_invalid_or_unresolvable_cost_never_publishes_interpolation(value):
    with pytest.raises(RoadCalculationError):
        refine_timed_path(POINTS, EDGES, 35, lambda candidate: value)


@pytest.mark.skipif(not os.environ.get('AIC_TIME_TEST_GRAPH'), reason='requires actual graph and native engine')
def test_native_time_prefix_stops_during_junction_transition():
    router = VehicleRouter(Path(os.environ['AIC_TIME_TEST_GRAPH']))
    start = RoadLocation(longitude=125.1852727, latitude=46.54446175)
    end = RoadLocation(longitude=125.18509545, latitude=46.5444392)
    vehicle = VehicleAssumption(kind='auto', source='explicit_reference_assumption')
    full = router.route_time_prefix(start, end, vehicle, 300)
    features = full['roads']['features']
    assert len(features) > 2
    assert full['roads']['properties']['path_completed'] is True
    for budget in (5., 35., 60.):
        prefix = router.route_time_prefix(start, end, vehicle, budget)
        boundary = prefix['roads']['features'][-1]['geometry']['coordinates'][-1]
        trip = router.route(start, RoadLocation(longitude=boundary[0], latitude=boundary[1]), vehicle)
        assert trip['reference_time_seconds'] <= budget + .1
    for i in range(1, len(features)):
        previous = features[i - 1]['properties']['arrival_seconds']
        departure = features[i]['properties']['departure_seconds']
        if departure - previous > .1:
            budget = (departure + previous) / 2
            partial = router.route_time_prefix(start, end, vehicle, budget)
            assert len(partial['roads']['features']) == i
            assert partial['roads']['features'][-1]['geometry'] == features[i - 1]['geometry']
            from app.services.road_worker_process import run_time_path_process
            isolated = run_time_path_process(Path(os.environ['AIC_TIME_TEST_GRAPH']), start, end,
                                            vehicle, budget, timeout_seconds=30)
            assert isolated == partial
            return
    pytest.fail('fixture must exercise nonzero junction transition')


@pytest.mark.skipif(not os.environ.get('AIC_TIME_TEST_GRAPH'), reason='requires actual graph and native engine')
@pytest.mark.parametrize('budget', [60, 180, 300, 600])
def test_native_time_branches_have_budget_verified_boundary_points(budget):
    router = VehicleRouter(Path(os.environ['AIC_TIME_TEST_GRAPH']))
    start = RoadLocation(longitude=125.1852727, latitude=46.54446175)
    vehicle = VehicleAssumption(kind='auto', source='explicit_reference_assumption')
    result = router.time_reachability(start, vehicle, budget)
    from app.services.road_worker_process import run_time_reachability_process
    isolated = run_time_reachability_process(Path(os.environ['AIC_TIME_TEST_GRAPH']), start, vehicle, budget)
    assert isolated == result
    assert result['branch_count'] > 1
    assert result['status'] == 'partial_reference'
    assert result['branch_reference_schema'] == 'shared-prefix-1'
    if budget == 600:
        assert any(branch['boundary_refinement_steps'] > 0 for branch in result['branches'])
    assert all(branch['boundary_verified_seconds'] is None or branch['boundary_verified_seconds'] <= budget
               for branch in result['branches'])
    for index, feature in enumerate(result['roads']['features']):
        parent = feature['properties']['parent_feature_index']
        assert parent is None or 0 <= parent < index
    from app.services.road_expansion_paths import trace_shape
    checked = 0
    for branch in result['branches']:
        features, seen = [], set()
        index = branch['tip_feature_index']
        while index is not None:
            assert index not in seen
            seen.add(index)
            feature = result['roads']['features'][index]
            features.append(feature)
            index = feature['properties']['parent_feature_index']
        features.reverse()
        if not features or not features[-1]['properties']['boundary_clipped']:
            continue
        points = []
        for feature in features:
            points.extend(feature['geometry']['coordinates'] if not points else feature['geometry']['coordinates'][1:])
        # Re-cost the ACTUAL candidate path. Calling route again can select a
        # different lower-penalty route with greater elapsed time; on this
        # graph a 180.006s candidate was re-routed to a distinct 191.583s path.
        expected_ids = [feature['properties']['edge_id'] for feature in features]
        trace = None
        for method, shape in [('edge_walk', [{'lon': x, 'lat': y, 'node_snap_tolerance': 0,
                                             'radius': 1, 'search_cutoff': 1} for x, y in points]),
                              ('map_snap', trace_shape(points))]:
            try:
                trace = router._actor.trace_attributes({'costing': 'auto', 'costing_options': {'auto': {}},
                    'units': 'kilometers', 'shape': shape, 'shape_match': method,
                    'filters': {'action': 'include', 'attributes': ['edge.id', 'node.elapsed_time']}})
            except Exception:
                continue
            if [edge['id'] for edge in trace['edges']] == expected_ids:
                break
        assert trace is not None
        actual_ids = [edge['id'] for edge in trace['edges']]
        if actual_ids == expected_ids[:-1]:
            # Native matching can collapse a sub-metre final sliver onto its
            # entry node (observed 0.388m / 0.028s). The full branch's IDs were
            # verified earlier; permit only this geometric round-trip limit,
            # never a missing full edge or a different approach.
            from app.services.road_reachability_geometry import _distance
            tail = features[-1]['geometry']['coordinates']
            assert sum(_distance(a, b) for a, b in zip(tail, tail[1:])) <= 1.
            assert budget - features[-1]['properties']['departure_seconds'] <= .1
        else:
            assert actual_ids == expected_ids
        assert trace['edges'][-1]['end_node']['elapsed_time'] <= budget + .1
        checked += 1
    assert checked


@pytest.mark.skipif(not os.environ.get('AIC_TIME_TEST_GRAPH'), reason='requires actual graph and native engine')
def test_dense_match_cannot_substitute_a_different_directed_road(monkeypatch):
    router = VehicleRouter(Path(os.environ['AIC_TIME_TEST_GRAPH']))
    original = router._actor.trace_attributes
    altered = []

    def wrong_road(payload):
        result = original(payload)
        if payload['shape_match'] == 'map_snap':
            result['edges'][0]['id'] += 1
            altered.append(True)
        return result

    monkeypatch.setattr(router._actor, 'trace_attributes', wrong_road)
    with pytest.raises(RoadCalculationError, match='^road_engine_response_invalid$'):
        router.time_reachability(RoadLocation(longitude=125.1852727, latitude=46.54446175),
            VehicleAssumption(kind='auto', source='explicit_reference_assumption'), 300)
    assert altered, 'fixture must exercise the dense matching verification'
