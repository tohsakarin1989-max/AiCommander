"""Read-only audit of the two observed public vector tile gaps (no network).

Requires the isolated map-build Python dependencies. Findings describe source
content, never geographic absence or road accessibility.
"""
import json
import hashlib
import math
from pathlib import Path
import sqlite3

import osmium
from shapely.geometry import LineString, Point, box, shape


def main():
    root = Path(__file__).resolve().parents[1] / 'backups/map-foundation/v4-source/20260908'
    cities = json.loads((root / 'two-city-region-v3/city-boundaries.geojson').read_text())
    targets = []
    invalid = {'nodes_without_location': 0, 'ways_without_complete_locations': 0}
    z, y = 15, 11657
    def latitude(row):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / 2 ** z))))
    for x in (27762, 27763):
        bounds = [x / 2 ** z * 360 - 180, latitude(y + 1), (x + 1) / 2 ** z * 360 - 180, latitude(y)]
        region = box(*bounds)
        targets.append({'xyz': [z, x, y], 'bounds': bounds, 'geometry': region,
                        'cities': [f['properties']['name'] for f in cities['features'] if shape(f['geometry']).intersects(region)],
                        'tagged_nodes': 0, 'intersecting_ways': 0, 'tagged_way_samples': []})

    class Sources(osmium.SimpleHandler):
        def node(self, node):
            if not node.location.valid():
                invalid['nodes_without_location'] += 1
                return
            if node.tags and node.location.valid():
                for item in targets:
                    if item['geometry'].covers(Point(node.location.lon, node.location.lat)):
                        item['tagged_nodes'] += 1

        def way(self, way):
            if not all(n.location.valid() for n in way.nodes):
                invalid['ways_without_complete_locations'] += 1
                return
            if len(way.nodes) < 2:
                return
            coords = [(n.lon, n.lat) for n in way.nodes]
            xs, ys = zip(*coords)
            for item in targets:
                west, south, east, north = item['bounds']
                overlaps = max(xs) >= west and min(xs) <= east and max(ys) >= south and min(ys) <= north
                if overlaps and LineString(coords).intersects(item['geometry']):
                    item['intersecting_ways'] += 1
                    if way.tags and len(item['tagged_way_samples']) < 20:
                        item['tagged_way_samples'].append({'osm_id': way.id, 'tags': dict(way.tags)})

    source_path = root / 'merged-three-regions-v1/merged.osm.pbf'
    with source_path.open('rb') as stream:
        source_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    Sources().apply_file(str(source_path), locations=True)
    with sqlite3.connect(f'file:{root}/vector-candidate-v2/two-city.mbtiles?mode=ro', uri=True) as db:
        for item in targets:
            z, x, y = item['xyz']
            item['stored_tiles'] = db.execute('SELECT count(*) FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?',
                                             (z, x, 2 ** z - 1 - y)).fetchone()[0]
            del item['geometry']
    print(json.dumps({'source_sha256': source_hash, 'invalid_locations': invalid, 'findings': targets,
                      'boundary': 'Public source node/way intersection only; enclosing relation polygons and real-world completeness are not proved.'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
