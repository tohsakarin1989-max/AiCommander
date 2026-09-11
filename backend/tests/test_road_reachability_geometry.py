import copy
import os
from pathlib import Path

import pytest

from app.services.road_reachability_geometry import INVALID_EDGE_ID, clip_distance_expansion
from app.services.vehicle_router import RoadCalculationError


def expansion():
    def edge(identifier, previous, distance, coordinates):
        return {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': coordinates},
                'properties': {'edge_id': identifier, 'pred_edge_id': previous,
                               'distance': distance, 'edge_status': 's', 'expansion_type': 0}}
    return {'type': 'FeatureCollection', 'properties': {'algorithm': 'dijkstras'}, 'features': [
        edge(1, INVALID_EDGE_ID, 38, [[125., 46.], [124.999, 46.]]),
        edge(2, INVALID_EDGE_ID, 38, [[124.999, 46.], [125., 46.]]),
        edge(3, 2, 638, [[125., 46.], [125., 46.002], [125.002, 46.002], [125.002, 46.]])]}


def test_frontier_does_not_publish_entire_over_budget_road():
    raw = expansion()
    original = copy.deepcopy(raw)
    result = clip_distance_expansion(raw, {1: .5, 2: .5}, 500)
    assert raw == original
    assert len(result['features']) == 3
    last = result['features'][-1]
    assert last['properties']['end_distance_m'] == 500
    assert last['properties']['boundary_clipped'] is True
    assert last['geometry']['coordinates'][-1] != [125.002, 46.]
    assert result['features'][0]['geometry']['coordinates'][0] == [124.9995, 46.]
    assert result['features'][1]['geometry']['coordinates'][0] == [124.9995, 46.]
    assert all(f['geometry']['type'] == 'LineString' for f in result['features'])


def test_small_budget_clips_seed_in_both_directions_without_full_road():
    result = clip_distance_expansion(expansion(), {1: .5, 2: .5}, 10)
    assert len(result['features']) == 2
    for feature in result['features']:
        assert feature['properties']['end_distance_m'] == 10
        assert feature['properties']['boundary_clipped'] is True
    endpoints = [f['geometry']['coordinates'][-1][0] for f in result['features']]
    assert 124.999 < endpoints[0] < 124.9995 < endpoints[1] < 125.


@pytest.mark.parametrize('fault', ['missing_seed', 'missing_predecessor', 'duplicate', 'nan', 'reverse', 'negative_delta'])
def test_incomplete_or_invalid_expansion_never_becomes_reachable_geometry(fault):
    raw, seeds = expansion(), {1: .5, 2: .5}
    properties = raw['features'][-1]['properties']
    if fault == 'missing_seed':
        seeds.pop(1)
    elif fault == 'missing_predecessor':
        properties['pred_edge_id'] = 999
    elif fault == 'duplicate':
        raw['features'].append(copy.deepcopy(raw['features'][0]))
    elif fault == 'nan':
        properties['distance'] = float('nan')
    elif fault == 'reverse':
        properties['expansion_type'] = 1
    else:
        properties['distance'] = 1
    with pytest.raises(RoadCalculationError, match='road_engine_response_invalid'):
        clip_distance_expansion(raw, seeds, 500)


@pytest.mark.skipif(not os.environ.get('AIC_CLOSED_TEST_GRAPH'), reason='requires built closed-road fixture')
def test_native_frontier_and_seed_geometry_are_clipped():
    from app.services.road_graph_artifact import graph_inventory_sha256
    from app.services.vehicle_router import VehicleRouter
    tiles = Path(os.environ['AIC_CLOSED_TEST_GRAPH'])
    assert graph_inventory_sha256(tiles) == '75d6ec33a3f0efbd8ac6630ef6ba781bfdfadbf6e92fd8729737662715896d6b'
    actor = VehicleRouter(tiles)._actor
    locations = [{'lon': 124.9995, 'lat': 46., 'radius': 30, 'search_cutoff': 30,
                  'node_snap_tolerance': 0, 'minimum_reachability': 0}]
    located = actor.locate({'costing': 'auto', 'locations': locations, 'verbose': True})
    seeds = {edge['edge_id']['value']: edge['percent_along'] for edge in located[0]['edges']}
    raw = actor.expansion({'action': 'isochrone', 'costing': 'auto', 'locations': locations,
                           'contours': [{'distance': .5}], 'dedupe': True, 'skip_opposites': False,
                           'expansion_properties': ['distance', 'edge_id', 'pred_edge_id',
                                                    'edge_status', 'expansion_type']})
    assert max(f['properties']['distance'] for f in raw['features']) == 638
    result = clip_distance_expansion(raw, seeds, 500)
    assert len(result['features']) == 3
    assert max(f['properties']['end_distance_m'] for f in result['features']) == 500
    boundary = [f for f in result['features'] if f['properties']['boundary_clipped']]
    assert len(boundary) == 1
    # The closed east-west shortcut must not appear. Reachable geometry stays
    # on the northern detour; the far endpoint of that detour is outside budget.
    assert boundary[0]['geometry']['coordinates'][-1][1] > 46.
    assert boundary[0]['geometry']['coordinates'][1] == [125., 46.002]
