import hashlib
import os

import pytest

osmium = pytest.importorskip('osmium', reason='optional offline build dependency')

from app.services.road_source_filter import filter_road_source


def fixture(path, restriction='no_left_turn', missing=False, multi_from=False, extra_tags=None):
    with osmium.SimpleWriter(str(path)) as writer:
        for i in range(1, 5):
            writer.add_node(osmium.osm.mutable.Node(id=i, location=(125 + i * .001, 46.), version=1))
        for identifier, nodes in ((10, [1, 2]), (20, [2, 3]), (30, [2, 4])):
            writer.add_way(osmium.osm.mutable.Way(id=identifier, nodes=nodes,
                tags={'highway': 'residential', 'name': '合成道路'}, version=1))
        writer.add_relation(osmium.osm.mutable.Relation(id=100, version=1,
            tags={'type': 'restriction', 'restriction': restriction, **(extra_tags or {})},
            members=[('w', 10, 'from'), ('n', 2, 'via'), ('w', 999 if missing else 20, 'to')]
                    + ([('w', 30, 'from')] if multi_from else [])))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_filter_keeps_order_tags_and_unaffected_restrictions(tmp_path):
    source = tmp_path / 'source.osm.pbf'
    digest = fixture(source)
    result = filter_road_source(source, tmp_path / 'out', excluded_way_ids={30}, expected_source_sha256=digest)
    assert result['counts'] == {'nodes': 4, 'ways': 2, 'relations': 1}
    found = {}
    class Read(osmium.SimpleHandler):
        def way(self, way):
            found[way.id] = ([node.ref for node in way.nodes], dict(way.tags))
    Read().apply_file(str(tmp_path / 'out' / 'eligible.osm.pbf'))
    assert set(found) == {10, 20} and found[20][0] == [2, 3]
    assert found[20][1]['name'] == '合成道路'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_no_turn_to_removed_way_is_no_longer_traversable(tmp_path):
    source = tmp_path / 'source.osm.pbf'
    digest = fixture(source)
    result = filter_road_source(source, tmp_path / 'out', excluded_way_ids={20}, expected_source_sha256=digest)
    assert result['dropped_relation_ids'] == [100]
    assert result['counts']['ways'] == 2


def test_only_turn_can_be_removed_when_all_approaches_are_excluded(tmp_path):
    source = tmp_path / 'source.osm.pbf'
    digest = fixture(source, restriction='only_right_turn')
    result = filter_road_source(source, tmp_path / 'out', excluded_way_ids={10}, expected_source_sha256=digest)
    assert result['dropped_relation_ids'] == [100]
    assert result['dropped_relation_reasons'][100] == 'all_from_ways_excluded'


def test_partial_multi_from_removal_does_not_drop_remaining_no_entry_restriction(tmp_path):
    source = tmp_path / 'source.osm.pbf'
    digest = fixture(source, restriction='no_entry', multi_from=True)
    result = filter_road_source(source, tmp_path / 'out', excluded_way_ids={30}, expected_source_sha256=digest)
    assert result['dropped_relation_ids'] == []
    assert result['rewritten_relations'][0]['relation_id'] == 100
    found = {}
    class Read(osmium.SimpleHandler):
        def relation(self, relation):
            found[relation.id] = (dict(relation.tags), [(m.type, m.ref, m.role) for m in relation.members])
    Read().apply_file(str(tmp_path / 'out' / 'eligible.osm.pbf'))
    assert found[100] == ({'type': 'restriction', 'restriction': 'no_entry'},
                          [('w', 10, 'from'), ('n', 2, 'via'), ('w', 20, 'to')])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize('kind', ['missing_reference', 'missing_exclusion'])
def test_no_silent_restriction_loss_or_missing_input(tmp_path, kind):
    source = tmp_path / 'source.osm.pbf'
    digest = fixture(source, restriction='only_right_turn' if kind == 'only' else 'no_left_turn',
                     missing=kind == 'missing_reference')
    with pytest.raises(ValueError):
        filter_road_source(source, tmp_path / 'out', excluded_way_ids={999 if kind == 'missing_exclusion' else 20},
                           expected_source_sha256=digest)
    assert not (tmp_path / 'out').exists()


def test_closed_only_target_rewrites_all_surviving_departures(tmp_path):
    source = tmp_path / 'source.osm.pbf'
    digest = fixture(source, restriction='only_right_turn')
    result = filter_road_source(source, tmp_path / 'out', excluded_way_ids={20}, expected_source_sha256=digest)
    assert result['dropped_relation_reasons'][100] == 'only_target_excluded_rewritten'
    generated = result['generated_turn_restrictions']
    assert {item['tags']['restriction'] for item in generated} == {'no_entry', 'no_u_turn'}
    assert {item['members'][-1][1] for item in generated} == {10, 30}
    assert all(item['source_relation_id'] == 100 for item in generated)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize('extra', [{'except': 'motorcar'}, {'except:conditional': 'hgv @ (Mo-Fr)'},
    {'restriction:conditional': 'only_right_turn @ (Mo-Fr)'}, {'restriction:hgv': 'only_left_turn'}])
def test_closed_only_target_does_not_flatten_exceptions(tmp_path, extra):
    source = tmp_path / 'source.osm.pbf'
    digest = fixture(source, restriction='only_right_turn', extra_tags=extra)
    with pytest.raises(ValueError, match='road_exclusion_requires_turn_rewrite'):
        filter_road_source(source, tmp_path / 'out', excluded_way_ids={20}, expected_source_sha256=digest)
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('nodes', [(1, 2, 5), (2, 1, 2)])
def test_only_rewrite_requires_unambiguous_endpoint_topology(nodes):
    from app.services.road_turn_rewrite import closed_only_target
    with pytest.raises(ValueError, match='requires_split_way'):
        closed_only_target({'type': 'restriction', 'restriction': 'only_right_turn'},
            [('w', 10, 'from'), ('n', 2, 'via'), ('w', 20, 'to')],
            {10: nodes, 20: (2, 3), 30: (2, 4)}, {20})


@pytest.mark.parametrize('restriction', ['only_right_turn', 'no_entry @ (Mo-Fr)', 'no_left_turn'])
def test_partial_approach_rewrite_rejects_other_restriction_semantics(tmp_path, restriction):
    source = tmp_path / 'source.osm.pbf'
    digest = fixture(source, restriction=restriction, multi_from=True)
    with pytest.raises(ValueError, match='road_exclusion_requires_turn_rewrite'):
        filter_road_source(source, tmp_path / 'out', excluded_way_ids={30}, expected_source_sha256=digest)
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('extra_tags', [{'except': 'motorcar'},
    {'restriction:conditional': 'no_entry @ (Mo-Fr)'}, {'restriction:hgv': 'only_right_turn'}])
def test_partial_approach_rewrite_does_not_flatten_exceptions_or_conditions(tmp_path, extra_tags):
    source = tmp_path / 'source.osm.pbf'
    digest = fixture(source, restriction='no_entry', multi_from=True, extra_tags=extra_tags)
    with pytest.raises(ValueError, match='road_exclusion_requires_turn_rewrite'):
        filter_road_source(source, tmp_path / 'out', excluded_way_ids={30}, expected_source_sha256=digest)
    assert not (tmp_path / 'out').exists()


@pytest.mark.skipif(os.environ.get('AIC_BUILD_ROAD_CONDITIONS') != '1', reason='optional real graph compilation')
@pytest.mark.parametrize('restriction_kind', ['no_entry', 'only_right_turn'])
def test_rewritten_no_entry_still_forces_native_route_and_matrix_detour(tmp_path, restriction_kind):
    from app.services.road_graph_builder import compile_local_graph
    from app.services.road_access_policy import VehicleAssumption
    from app.services.vehicle_router import RoadLocation, VehicleRouter

    points = {1: (125., 46.), 2: (125.002, 46.), 3: (125.004, 46.),
              4: (125.002, 46.002), 5: (125., 45.998), 6: (125.004, 45.998),
              7: (124.999, 46.), 8: (125.005, 46.)}
    distances = {}
    for restricted in (False, True):
        source = tmp_path / f'source-{restricted}.osm.pbf'
        with osmium.SimpleWriter(str(source)) as writer:
            for identifier, coordinates in points.items():
                writer.add_node(osmium.osm.mutable.Node(id=identifier, location=coordinates, version=1))
            for identifier, nodes in ((10, [1, 2]), (20, [2, 3]), (30, [4, 2]),
                                      (40, [1, 5, 6, 3]), (50, [7, 1]), (60, [3, 8])):
                writer.add_way(osmium.osm.mutable.Way(id=identifier, nodes=nodes, version=1,
                    tags={'highway': 'residential', 'maxspeed': '30', 'motor_vehicle': 'yes'}))
            if restricted:
                writer.add_relation(osmium.osm.mutable.Relation(id=100, version=1,
                    tags={'type': 'restriction', 'restriction': restriction_kind},
                    members=([('w', 10, 'from'), ('w', 30, 'from'), ('n', 2, 'via'), ('w', 20, 'to')]
                             if restriction_kind == 'no_entry' else [('w', 10, 'from'), ('n', 2, 'via'), ('w', 30, 'to')])))
        filtered = tmp_path / f'filtered-{restricted}'
        compiled = tmp_path / f'compiled-{restricted}'
        report = filter_road_source(source, filtered, excluded_way_ids={30},
            expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        compile_local_graph(filtered / 'eligible.osm.pbf', compiled,
                            expected_source_sha256=report['output_sha256'])
        router = VehicleRouter(compiled / 'tiles')
        start = RoadLocation(longitude=124.9995, latitude=46.)
        end = RoadLocation(longitude=125.0045, latitude=46.)
        for kind in ('auto', 'truck'):
            vehicle = VehicleAssumption(kind=kind, source='case_record',
                height_m=2.5 if kind == 'truck' else None, weight_t=5. if kind == 'truck' else None)
            route = router.route(start, end, vehicle)
            matrix = router.matrix([start], [end], vehicle)
            assert (40 in route['way_ids']) is restricted
            assert abs(route['distance_m'] - matrix['cells'][0]['distance_m']) <= 5
            distances[restricted, kind] = route['distance_m']
            reverse = router.route(end, start, vehicle)
            assert 40 not in reverse['way_ids']
    for kind in ('auto', 'truck'):
        assert distances[True, kind] > distances[False, kind] + 300


def test_condition_overlay_preserves_geometry_and_turn_relations(tmp_path):
    source = tmp_path / 'source.osm.pbf'
    digest = fixture(source)
    overlay = {'geometry': {'type': 'LineString', 'coordinates': [[125.002, 46.], [125.003, 46.]]},
               'conditions': {'direction': 'reverse', 'gate': 'open', 'access': 'permitted',
                              'max_height_m': 3., 'max_weight_t': 10.}}
    result = filter_road_source(source, tmp_path / 'out', excluded_way_ids=set(),
                               expected_source_sha256=digest, condition_overlays={20: overlay})
    assert result['condition_overlay_way_ids'] == [20]
    assert result['counts'] == {'nodes': 4, 'ways': 3, 'relations': 1}
    found = {}
    class Read(osmium.SimpleHandler):
        def way(self, way):
            found[way.id] = ([node.ref for node in way.nodes], dict(way.tags))
    Read().apply_file(str(tmp_path / 'out' / 'eligible.osm.pbf'))
    assert found[20][0] == [2, 3]
    assert found[20][1]['oneway'] == '-1'
    assert found[20][1]['maxheight'] == '3' and found[20][1]['maxweight'] == '10'
    assert 'oneway' not in found[10][1]


def test_public_private_way_is_removed_unless_governed_full_way_overlay_is_present(tmp_path):
    source = tmp_path / 'private.osm.pbf'
    with osmium.SimpleWriter(str(source)) as writer:
        for identifier, lon in ((1, 125.), (2, 125.001)):
            writer.add_node(osmium.osm.mutable.Node(id=identifier, location=(lon, 46.), version=1))
        writer.add_way(osmium.osm.mutable.Way(id=10, nodes=[1, 2], version=1,
            tags={'highway': 'service', 'access': 'private'}))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    requested = set()
    public = filter_road_source(source, tmp_path / 'public', excluded_way_ids=requested, expected_source_sha256=digest)
    assert public['excluded_way_ids'] == [10] and requested == set()
    assert public['counts']['ways'] == 0
    assert public['public_access_exclusions'][0]['reason'] == 'public_access_not_authorized'
    overlay = {'geometry': {'type': 'LineString', 'coordinates': [[125., 46.], [125.001, 46.]]},
               'conditions': {'direction': 'both', 'access': 'permitted', 'gate': 'open'}}
    governed = filter_road_source(source, tmp_path / 'governed', excluded_way_ids=set(),
        expected_source_sha256=digest, condition_overlays={10: overlay})
    assert governed['counts']['ways'] == 1 and governed['excluded_way_ids'] == []


@pytest.mark.skipif(os.environ.get('AIC_BUILD_ROAD_CONDITIONS') != '1', reason='optional real graph compilation')
@pytest.mark.parametrize('public_private', [False, True])
def test_compiled_oneway_height_and_weight_change_actual_route_and_matrix(tmp_path, public_private):
    from app.services.road_graph_builder import compile_local_graph
    from app.services.road_access_policy import VehicleAssumption
    from app.services.vehicle_router import RoadLocation, VehicleRouter
    source = tmp_path / 'synthetic.osm.pbf'
    points = {1: (124.999, 46.), 2: (125., 46.), 3: (125.002, 46.),
              4: (125., 46.002), 5: (125.002, 46.002), 6: (125.003, 46.)}
    with osmium.SimpleWriter(str(source)) as writer:
        for identifier, coordinates in sorted(points.items()):
            writer.add_node(osmium.osm.mutable.Node(id=identifier, location=coordinates, version=1))
        for identifier, nodes in ((1, [1, 2]), (10, [2, 3]), (20, [2, 4, 5, 3]), (30, [3, 6])):
            tags = {'highway': 'residential', 'maxspeed': '30', 'motor_vehicle': 'yes'}
            if public_private and identifier == 10:
                tags['motor_vehicle'] = 'private'
            writer.add_way(osmium.osm.mutable.Way(id=identifier, nodes=nodes, version=1,
                tags=tags))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    overlay = {'geometry': {'type': 'LineString', 'coordinates': [list(points[2]), list(points[3])]},
               'conditions': {'direction': 'forward', 'gate': 'open', 'access': 'permitted',
                              'max_height_m': 3., 'max_weight_t': 10.}}
    report = filter_road_source(source, tmp_path / 'filtered', excluded_way_ids=set(),
                                expected_source_sha256=digest, condition_overlays={} if public_private else {10: overlay},
                                vehicle_kind='truck')
    compile_local_graph(tmp_path / 'filtered' / 'eligible.osm.pbf', tmp_path / 'compiled',
                        expected_source_sha256=report['output_sha256'])
    router = VehicleRouter(tmp_path / 'compiled' / 'tiles')
    start = RoadLocation(longitude=124.9995, latitude=46.)
    end = RoadLocation(longitude=125.0025, latitude=46.)
    distances = {}
    for name, origin, target, height, weight in (
        ('normal', start, end, 2.5, 5.), ('reverse', end, start, 2.5, 5.),
        ('tall', start, end, 3.5, 5.), ('heavy', start, end, 2.5, 12.),
    ):
        vehicle = VehicleAssumption(kind='truck', height_m=height, weight_t=weight, source='case_record')
        route = router.route(origin, target, vehicle)
        matrix = router.matrix([origin], [target], vehicle)
        distances[name] = route['distance_m']
        assert (10 in route['way_ids']) == (name == 'normal' and not public_private)
        assert abs(route['distance_m'] - matrix['cells'][0]['distance_m']) <= 5
    if public_private:
        assert report['excluded_way_ids'] == [10]
        assert all(distance > 600 for distance in distances.values())
    else:
        assert all(distances[name] > distances['normal'] + 300 for name in ('reverse', 'tall', 'heavy'))
