import hashlib
import os

import pytest

osmium = pytest.importorskip('osmium', reason='optional local PBF dependency')

from app.services.road_source_filter import filter_road_source


def source_fixture(path, *, duplicate=False):
    points = {1: [125., 46.], 2: [125.001, 46.], 3: [125.002, 46.], 4: [125.003, 46.]}
    with osmium.SimpleWriter(str(path)) as writer:
        for identifier, coordinates in points.items():
            writer.add_node(osmium.osm.mutable.Node(id=identifier, location=coordinates, version=1))
        ways = [(10, [1, 2]), (20, [3, 4])]
        if duplicate:
            ways.append((30, [3, 4]))
        for identifier, nodes in ways:
            writer.add_way(osmium.osm.mutable.Way(id=identifier, nodes=nodes, version=1,
                                                 tags={'highway': 'residential'}))
    overlay = {'geometry': {'type': 'MultiLineString', 'coordinates': [
        [points[1], points[2]], [points[4], points[3]]]},
        'conditions': {'direction': 'forward', 'access': 'permitted', 'gate': 'open'}}
    return hashlib.sha256(path.read_bytes()).hexdigest(), overlay


def test_disjoint_components_preserve_gap_and_individual_direction(tmp_path):
    source = tmp_path / 'source.osm.pbf'
    digest, overlay = source_fixture(source)
    result = filter_road_source(source, tmp_path / 'out', excluded_way_ids=set(),
        expected_source_sha256=digest, condition_overlays={10: overlay, 20: overlay})
    assert result['condition_overlay_way_ids'] == [10, 20]
    assert [r['component_index'] for r in result['component_references']] == [0, 1]
    assert [r['reversed'] for r in result['component_references']] == [False, True]
    ways = {}
    class Read(osmium.SimpleHandler):
        def way(self, way):
            ways[way.id] = ([node.ref for node in way.nodes], dict(way.tags))
    Read().apply_file(str(tmp_path / 'out' / 'eligible.osm.pbf'))
    assert ways[10] == ([1, 2], {'highway': 'residential', 'oneway': 'yes'})
    assert ways[20] == ([3, 4], {'highway': 'residential', 'oneway': '-1'})
    assert result['counts']['nodes'] == 4
    assert not set(ways[10][0]).intersection(ways[20][0])


@pytest.mark.parametrize('fault', ['missing', 'duplicate'])
def test_incomplete_or_duplicate_component_mapping_never_emits_eligible_source(tmp_path, fault):
    source = tmp_path / 'source.osm.pbf'
    digest, overlay = source_fixture(source, duplicate=fault == 'duplicate')
    mappings = {10: overlay} if fault == 'missing' else {10: overlay, 20: overlay, 30: overlay}
    with pytest.raises(ValueError, match='component_correspondence'):
        filter_road_source(source, tmp_path / 'out', excluded_way_ids=set(),
                           expected_source_sha256=digest, condition_overlays=mappings)
    assert not (tmp_path / 'out').exists()


def test_exclusion_wins_but_does_not_hide_missing_component_coverage(tmp_path):
    source = tmp_path / 'source.osm.pbf'
    digest, overlay = source_fixture(source)
    result = filter_road_source(source, tmp_path / 'out', excluded_way_ids={20},
        expected_source_sha256=digest, condition_overlays={10: overlay, 20: overlay})
    assert result['condition_overlay_way_ids'] == [10]
    assert result['counts']['ways'] == 1
    assert result['component_references'][1]['excluded'] is True


@pytest.mark.skipif(os.environ.get('AIC_BUILD_ROAD_CONDITIONS') != '1', reason='optional real graph compilation')
def test_native_graph_does_not_connect_disjoint_components(tmp_path):
    from app.services.road_graph_builder import compile_local_graph
    from app.services.road_access_policy import VehicleAssumption
    from app.services.vehicle_router import RoadCalculationError, RoadLocation, VehicleRouter
    source = tmp_path / 'source.osm.pbf'
    digest, overlay = source_fixture(source)
    report = filter_road_source(source, tmp_path / 'out', excluded_way_ids=set(),
        expected_source_sha256=digest, condition_overlays={10: overlay, 20: overlay})
    compile_local_graph(tmp_path / 'out' / 'eligible.osm.pbf', tmp_path / 'compiled',
                        expected_source_sha256=report['output_sha256'])
    router = VehicleRouter(tmp_path / 'compiled' / 'tiles')
    vehicle = VehicleAssumption(kind='auto', source='explicit_reference_assumption')
    origin = RoadLocation(longitude=125.0002, latitude=46.)
    same_segment = RoadLocation(longitude=125.0008, latitude=46.)
    assert router.route(origin, same_segment, vehicle)['way_ids'] == [10]
    disconnected = RoadLocation(longitude=125.0025, latitude=46.)
    with pytest.raises(RoadCalculationError, match='road_engine_calculation_failed'):
        router.route(origin, disconnected, vehicle)
