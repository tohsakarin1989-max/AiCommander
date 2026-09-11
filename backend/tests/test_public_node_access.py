import hashlib
import os

import pytest

from app.services.public_road_access import public_node_access


@pytest.mark.parametrize('tags,allowed', [
    ({}, True), ({'barrier': 'gate'}, False), ({'barrier': 'gate', 'access': 'yes'}, True),
    ({'barrier': 'gate', 'access': 'yes', 'locked': 'yes'}, False),
    ({'barrier': 'gate', 'access': 'private', 'motorcar': 'yes'}, True),
    ({'barrier': 'gate', 'motorcar': 'yes', 'opening_hours': 'Mo-Fr 08:00-17:00'}, False),
    ({'barrier': 'gate', 'access:conditional': 'yes @ (Mo-Fr)'}, False),
    ({'access': 'no'}, False), ({'barrier': 'bollard', 'access': 'yes'}, False),
    ({'barrier': 'unknown-new-kind', 'access': 'yes'}, False),
])
def test_node_permission_is_not_inferred_from_road(tags, allowed):
    assert public_node_access(tags, 'auto')['include'] is allowed


def write_source(path, tags):
    osmium = pytest.importorskip('osmium')
    points = {1: [125, 46], 2: [125.002, 46], 3: [125.004, 46],
              4: [125, 46.02], 5: [125.004, 46.02]}
    with osmium.SimpleWriter(str(path)) as writer:
        for identifier, coordinates in points.items():
            writer.add_node(osmium.osm.mutable.Node(id=identifier, location=coordinates, version=1,
                                                   tags=tags if identifier == 2 else {}))
        for identifier, nodes in [(10, [1, 2, 3]), (20, [1, 4, 5, 3])]:
            writer.add_way(osmium.osm.mutable.Way(id=identifier, nodes=nodes, version=1,
                tags={'highway': 'residential', 'motor_vehicle': 'yes'}))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('extra', [{}, {'motorcar:conditional': 'yes @ (Mo-Fr)',
                                     'hgv:conditional': 'yes @ (Mo-Fr)'}])
def test_unknown_gate_retains_road_geometry_but_compiles_node_denial(tmp_path, extra):
    osmium = pytest.importorskip('osmium')
    from app.services.road_source_filter import filter_road_source
    source = tmp_path / 'source.osm.pbf'
    digest = write_source(source, {'barrier': 'gate', **extra})
    result = filter_road_source(source, tmp_path / 'out', excluded_way_ids=set(), expected_source_sha256=digest)
    assert result['counts']['ways'] == 2 and result['excluded_way_ids'] == []
    reason = 'public_access_condition_unresolved' if extra else 'node_gate_permission_unknown'
    assert result['node_access_restrictions'] == [{'node_id': 2, 'include': False, 'reason': reason}]
    nodes = {}
    class Read(osmium.SimpleHandler):
        def node(self, node):
            nodes[node.id] = dict(node.tags)
    Read().apply_file(str(tmp_path / 'out/eligible.osm.pbf'))
    assert nodes[2]['motorcar'] == nodes[2]['hgv'] == 'no'
    assert not any(key in nodes[2] for key in extra)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


@pytest.mark.skipif(os.environ.get('AIC_BUILD_ROAD_CONDITIONS') != '1', reason='requires native graph compiler')
def test_real_node_gate_enforced_by_route_matrix_and_reachability(tmp_path):
    from app.services.road_source_filter import filter_road_source
    from app.services.road_graph_builder import compile_local_graph
    from app.services.road_access_policy import VehicleAssumption
    from app.services.vehicle_router import VehicleRouter, RoadLocation
    origin = RoadLocation(longitude=125.0002, latitude=46)
    target = RoadLocation(longitude=125.0038, latitude=46)
    distances = {}
    for name, tags in [('allowed', {'barrier': 'gate', 'access': 'yes'}),
                       ('unknown', {'barrier': 'gate'}),
                       ('denied', {'barrier': 'gate', 'access': 'no'}),
                       ('conditional', {'barrier': 'gate', 'access': 'no',
                           'motorcar:conditional': 'yes @ (Mo-Fr)', 'hgv:conditional': 'yes @ (Mo-Fr)'})]:
        source = tmp_path / f'{name}.osm.pbf'
        digest = write_source(source, tags)
        result = filter_road_source(source, tmp_path / name, excluded_way_ids=set(), expected_source_sha256=digest)
        compile_local_graph(tmp_path / name / 'eligible.osm.pbf', tmp_path / f'compiled-{name}',
                            expected_source_sha256=result['output_sha256'])
        router = VehicleRouter(tmp_path / f'compiled-{name}/tiles')
        for kind in ['auto', 'truck']:
            vehicle = VehicleAssumption(kind=kind, height_m=2 if kind == 'truck' else None,
                                       weight_t=3 if kind == 'truck' else None, source='explicit_reference_assumption')
            route = router.route(origin, target, vehicle)
            matrix = router.matrix([origin], [target], vehicle)
            assert abs(matrix['cells'][0]['distance_m'] - route['distance_m']) <= 5
            assert (20 in route['way_ids']) is (name != 'allowed')
            distances[name, kind] = route['distance_m']
            reachable = router.distance_reachability(origin, vehicle, 500)
            # The detour is over 4 km, so within 500 m the far side of
            # the gate can only be reached by crossing the gate itself.
            far_side = any(point[0] > 125.00201 and abs(point[1] - 46) < .000001
                for feature in reachable['roads']['features']
                for point in feature['geometry']['coordinates'])
            assert far_side is (name == 'allowed')
            assert all(feature['properties']['end_distance_m'] <= 500
                       for feature in reachable['roads']['features'])
            timed = router.time_reachability(origin, vehicle, 60)
            timed_far_side = any(point[0] > 125.00201 and abs(point[1] - 46) < .000001
                for feature in timed['roads']['features']
                for point in feature['geometry']['coordinates'])
            assert timed_far_side is (name == 'allowed')
    for kind in ['auto', 'truck']:
        assert distances['unknown', kind] > distances['allowed', kind] * 3
        assert distances['unknown', kind] == distances['denied', kind]
        assert distances['conditional', kind] == distances['denied', kind]
