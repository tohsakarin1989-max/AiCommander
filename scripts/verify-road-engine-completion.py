"""Native completion regression; synthetic roads only, supports old/new engine.

prepare creates an isolated PBF; verify builds it and exercises the actual Actor.
Use --expect-legacy only to reproduce upstream swallowing of a thor error.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def prepare(root):
    import osmium
    root.mkdir(parents=True, exist_ok=True)
    nodes = {1: (125., 46.), 2: (125.002, 46.), 3: (125.004, 46.),
             4: (125.002, 46.002), 5: (125.05, 46.), 6: (125.052, 46.)}
    with osmium.SimpleWriter(str(root / 'source.osm.pbf')) as writer:
        for identifier, point in nodes.items():
            writer.add_node(osmium.osm.mutable.Node(id=identifier, location=point, version=1))
        for identifier, points in ((10, [1, 2, 3]), (20, [2, 4]), (30, [5, 6])):
            writer.add_way(osmium.osm.mutable.Way(id=identifier, nodes=points, version=1,
                tags={'highway': 'residential', 'maxspeed': '30'}))


def verify(source, output, legacy):
    from valhalla import Actor, PYVALHALLA_DIR
    from valhalla.config import get_config
    output.mkdir(parents=True, exist_ok=False)
    tiles = output / 'tiles'
    tiles.mkdir()
    config = get_config(tile_dir=str(tiles), tile_extract='')
    config['mjolnir'].update(tile_url='', traffic_extract='', admin='', timezone='')
    config['mjolnir']['data_processing'].update(use_admin_db=False, apply_country_overrides=False,
        infer_internal_intersections=False, infer_turn_channels=False)
    config_path = output / 'config.json'
    config_path.write_text(json.dumps(config))
    with (output / 'build.log').open('w') as log:
        subprocess.run([str(PYVALHALLA_DIR / 'bin/valhalla_build_tiles'), '-j', '1',
            '-c', str(config_path), str(source)], check=True, timeout=120, stdout=log, stderr=subprocess.STDOUT)
    report = {'passed': False, 'expected_legacy': legacy,
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    try:
        actor = Actor(config)
        start = {'lon': 125.0005, 'lat': 46., 'radius': 5, 'search_cutoff': 5, 'minimum_reachability': 0}
        other = {'lon': 125.0505, 'lat': 46., 'radius': 5, 'search_cutoff': 5, 'minimum_reachability': 0}
        failed_request = {'costing': 'auto', 'locations': [start, other]}
        try:
            actor.route(failed_request)
        except Exception as error:
            report['route_error_code'] = getattr(error, 'code', None)
        assert report.get('route_error_code') == 442, 'fixture must reach thor no-path error, not input validation'
        try:
            partial = actor.expansion({**failed_request, 'action': 'route', 'generalize': 0})
            report['expansion_returned_partial'] = partial.get('type') == 'FeatureCollection'
        except Exception as error:
            report['expansion_error_code'] = getattr(error, 'code', None)
        if legacy:
            assert report.get('expansion_returned_partial') is True
        else:
            assert report.get('expansion_error_code') == 442
            assert 'expansion_returned_partial' not in report
        # Exercise the same actor after exceptional expansion cleanup.
        for metric, budget in [('distance', .3), ('time', 1)]:
            result = actor.expansion({'costing': 'auto', 'action': 'isochrone', 'locations': [start],
                'contours': [{metric: budget}], 'generalize': 0, 'dedupe': True,
                'skip_opposites': False, 'expansion_properties': ['edge_id', 'pred_edge_id', 'edge_status']})
            assert result['features']
            marker = result.get('properties', {}).get('aicommander_expansion_contract')
            assert marker == (None if legacy else 'completed-v1')
            report[metric] = {'feature_count': len(result['features']), 'completion_contract': marker}
        report['passed'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--expect-legacy', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prepare.resolve())
    elif args.source and args.output:
        verify(args.source.resolve(strict=True), args.output.resolve(), args.expect_legacy)
    else:
        parser.error('use --prepare or --source and --output')
