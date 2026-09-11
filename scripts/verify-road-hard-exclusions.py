#!/usr/bin/env python3
"""Synthetic source -> real Valhalla graphs -> route/matrix hard-exclusion check.

Requires local osmium, pyvalhalla 3.8.3 and backend dependencies. No production
database, map publication or remote access. This is not the production compiler.
"""
import json
import hashlib
from pathlib import Path
import sys
import tempfile

import osmium

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.services.road_access_policy import InternalRoadConditions, VehicleAssumption, internal_road_eligibility
from app.services.road_graph_artifact import graph_inventory_sha256
from app.services.road_graph_builder import compile_local_graph
from app.services.road_source_filter import filter_road_source
from app.services.vehicle_router import RoadLocation, VehicleRouter
from datetime import datetime, timezone


POINTS = {1: (124.999, 46.), 2: (125., 46.), 3: (125.002, 46.),
          4: (125., 46.002), 5: (125.002, 46.002), 6: (125.003, 46.)}
AT = datetime(2026, 9, 11, tzinfo=timezone.utc)
VEHICLE = VehicleAssumption(kind='auto', source='explicit_reference_assumption')


def write_fixture(path, include_shortcut):
    ways = {1: [1, 2], 20: [2, 4, 5, 3], 30: [3, 6]}
    if include_shortcut:
        ways[10] = [2, 3]
    with osmium.SimpleWriter(str(path)) as writer:
        for identifier, coordinates in sorted(POINTS.items()):
            writer.add_node(osmium.osm.mutable.Node(id=identifier, location=coordinates, version=1))
        for identifier, nodes in sorted(ways.items()):
            writer.add_way(osmium.osm.mutable.Way(id=identifier, nodes=nodes, version=1,
                tags={'highway': 'residential', 'maxspeed': '30', 'motor_vehicle': 'yes'}))
    return sorted(ways)


def build(directory, include_shortcut):
    directory.mkdir()
    source = directory / 'synthetic.osm.pbf'
    way_ids = write_fixture(source, True)
    with source.open('rb') as stream:
        source_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    filtered = filter_road_source(source, directory / 'filtered',
        excluded_way_ids=set() if include_shortcut else {10}, expected_source_sha256=source_hash)
    source = directory / 'filtered' / 'eligible.osm.pbf'
    source_hash = filtered['output_sha256']
    way_ids = [identifier for identifier in way_ids if identifier not in filtered['excluded_way_ids']]
    try:
        compile_local_graph(source, directory / 'bad-source', expected_source_sha256='0' * 64)
    except ValueError as error:
        assert str(error) == 'road_graph_source_checksum_mismatch'
    else:
        raise AssertionError('Incorrect source hash accepted')
    assert not (directory / 'bad-source').exists()
    built = compile_local_graph(source, directory / 'compiled', expected_source_sha256=source_hash)
    assert built['status'] == 'built_not_published'
    try:
        compile_local_graph(source, directory / 'compiled', expected_source_sha256=source_hash)
    except FileExistsError:
        pass
    else:
        raise AssertionError('Existing graph output overwritten')
    tiles = directory / 'compiled' / 'tiles'
    router = VehicleRouter(tiles)
    start = RoadLocation(longitude=124.9995, latitude=46.)
    end = RoadLocation(longitude=125.0025, latitude=46.)
    route = router.route(start, end, VEHICLE)
    matrix = router.matrix([start], [end], VEHICLE)
    return {'source_way_ids': way_ids, 'graph_sha256': graph_inventory_sha256(tiles),
            'distance_m': route['distance_m'], 'route_way_ids': route['way_ids'],
            'matrix_distance_m': matrix['cells'][0]['distance_m']}


def main():
    root = ROOT / 'output' / 'validation'
    root.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='road-hard-exclusions-', dir=root))
    normal = InternalRoadConditions(direction='both', gate='open', access='permitted')
    decisions = {}
    for name, conditions, permission, verified in (
        ('open', normal, True, True),
        ('closed', normal.model_copy(update={'gate': 'closed'}), True, True),
        ('no_permit', normal, False, True),
        ('unknown_gate', normal.model_copy(update={'gate': 'unknown'}), True, True),
        ('unverified', normal, True, False),
    ):
        decision = internal_road_eligibility(conditions=conditions, vehicle=VEHICLE,
            traversal_permitted=permission, verified=verified, at=AT)
        decisions[name] = {'include': decision.include, 'reason': decision.reason}
    assert decisions['open']['include'] and not any(decisions[key]['include'] for key in decisions if key != 'open')
    opened = build(output / 'open', decisions['open']['include'])
    closed = build(output / 'closed', decisions['closed']['include'])
    assert 10 in opened['route_way_ids'] and 10 not in closed['source_way_ids']
    assert 10 not in closed['route_way_ids'] and 20 in closed['route_way_ids']
    assert closed['distance_m'] > opened['distance_m'] + 300
    for result in (opened, closed):
        assert abs(result['distance_m'] - result['matrix_distance_m']) <= 5
    report = {'synthetic_only': True, 'engine_version': '3.8.3', 'decisions': decisions,
              'open': opened, 'closed': closed, 'passed': True,
              'boundary': 'Two real graphs built. Other policy cases share exclusion decision only; production compiler, junction governance and permissions integration not certified.'}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'report': str(output / 'report.json'), **report}, ensure_ascii=False))


if __name__ == '__main__':
    main()
