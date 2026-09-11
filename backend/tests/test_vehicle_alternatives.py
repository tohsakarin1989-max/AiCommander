"""Opt-in native graph: two genuine corridors, lower one has a height restriction."""
import json
import os
import subprocess

import pytest

from app.services.vehicle_router import VehicleRouter, RoadLocation
from app.services.road_access_policy import VehicleAssumption


@pytest.mark.skipif(os.environ.get('AIC_BUILD_ALTERNATIVE_GRAPH') != '1', reason='requires native graph builder and pyosmium')
def test_native_distinct_corridors_and_truck_hard_limit(tmp_path):
    import osmium
    from valhalla import PYVALHALLA_DIR
    from valhalla.config import get_config
    nodes = {1: (125., 46.), 2: (125.002, 46.), 3: (125.005, 46.0025),
             4: (125.018, 46.0025), 5: (125.021, 46.), 6: (125.023, 46.),
             7: (125.005, 45.9975), 8: (125.018, 45.9975)}
    source = tmp_path / 'corridors.osm.pbf'
    with osmium.SimpleWriter(str(source)) as writer:
        for identifier, point in nodes.items():
            writer.add_node(osmium.osm.mutable.Node(id=identifier, location=point, version=1))
        for identifier, points in ((10, [1, 2]), (20, [2, 3, 4, 5]), (30, [2, 7, 8, 5]), (40, [5, 6])):
            tags = {'highway': 'residential', 'maxspeed': '40', 'name': f'synthetic-{identifier}'}
            if identifier == 30:
                tags['maxheight'] = '2.5'
            writer.add_way(osmium.osm.mutable.Way(id=identifier, nodes=points, version=1, tags=tags))
    tiles = tmp_path / 'tiles'
    tiles.mkdir()
    config = get_config(tile_dir=str(tiles), tile_extract='')
    config['mjolnir'].update(tile_url='', traffic_extract='', admin='', timezone='')
    config['mjolnir']['data_processing'].update(use_admin_db=False, apply_country_overrides=False,
        infer_internal_intersections=False, infer_turn_channels=False)
    config_path = tmp_path / 'config.json'
    config_path.write_text(json.dumps(config))
    with (tmp_path / 'build.log').open('w') as log:
        subprocess.run([str(PYVALHALLA_DIR / 'bin/valhalla_build_tiles'), '-j', '1', '-c', str(config_path), str(source)],
                       check=True, timeout=90, stdout=log, stderr=subprocess.STDOUT)
    router = VehicleRouter(tiles)
    start = RoadLocation(longitude=125.0005, latitude=46.)
    end = RoadLocation(longitude=125.0225, latitude=46.)
    car = router.route(start, end, VehicleAssumption(kind='auto', source='explicit_reference_assumption'))
    assert len(car['alternatives']) == 1, car
    primary, alternate = set(car['way_ids']), set(car['alternatives'][0]['way_ids'])
    assert primary != alternate and primary | alternate == {10, 20, 30, 40}
    truck = router.route(start, end, VehicleAssumption(kind='truck', source='explicit_reference_assumption', height_m=3.2, weight_t=8.))
    assert 30 not in truck['way_ids'] and truck['alternatives'] == []
    if os.environ.get('AIC_ALTERNATIVE_EVIDENCE'):
        from pathlib import Path
        evidence = Path(os.environ['AIC_ALTERNATIVE_EVIDENCE'])
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / 'report.json').write_text(json.dumps({'passed': True, 'synthetic_native_graph': True,
            'car': car, 'truck': truck}, ensure_ascii=False, indent=2))
