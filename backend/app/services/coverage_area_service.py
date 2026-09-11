"""PostGIS nominal circle union inside a registered boundary; no pixel estimates."""
import json
import math

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

VERSION = 'nominal-area-4.4-1'


def _geometry(boundary):
    kind = 'registered_polygon'
    if isinstance(boundary, list) and len(boundary) == 4:
        west, south, east, north = boundary
        if not all(type(value) in (int, float) and math.isfinite(value) for value in boundary):
            raise ValueError('boundary_invalid')
        if west >= east or south >= north:
            raise ValueError('boundary_invalid')
        boundary = {'type': 'Polygon', 'coordinates': [[[west, south], [east, south],
                    [east, north], [west, north], [west, south]]]}
        kind = 'registered_bbox_not_exact_factory_boundary'
    if isinstance(boundary, dict) and boundary.get('type') == 'Feature':
        boundary = boundary.get('geometry')
    if not isinstance(boundary, dict) or boundary.get('type') not in ('Polygon', 'MultiPolygon'):
        raise ValueError('boundary_missing')
    polygons = [boundary.get('coordinates')] if boundary['type'] == 'Polygon' else boundary.get('coordinates')
    points = []
    if not isinstance(polygons, list) or not polygons:
        raise ValueError('boundary_invalid')
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ValueError('boundary_invalid')
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError('boundary_invalid')
            for point in ring:
                if (not isinstance(point, list) or len(point) != 2
                        or not all(type(value) in (int, float) and math.isfinite(value) for value in point)
                        or not -180 <= point[0] <= 180 or not -85 <= point[1] <= 85):
                    raise ValueError('boundary_invalid')
                points.append(point)
                if len(points) > 50000:
                    raise ValueError('boundary_too_complex')
    if max(point[0] for point in points) - min(point[0] for point in points) > 20:
        raise ValueError('boundary_requires_regional_partition')
    return boundary, kind


AREA_SQL = text("""
WITH boundary AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:boundary),4326) AS geom),
valid_boundary AS (SELECT geom FROM boundary WHERE ST_IsValid(geom) AND NOT ST_IsEmpty(geom)),
circles AS (
 SELECT row_number() OVER () AS id,
 ST_CollectionExtract(ST_Intersection(b.geom,
   CAST(ST_Buffer(CAST(ST_SetSRID(ST_MakePoint(r.lon,r.lat),4326) AS geography),r.radius,32) AS geometry)),3) AS geom
 FROM jsonb_to_recordset(CAST(:resources AS jsonb)) AS r(lon double precision, lat double precision, radius double precision)
 CROSS JOIN valid_boundary b
), covered AS (SELECT ST_UnaryUnion(ST_Collect(geom)) AS geom FROM circles),
overlap AS (SELECT ST_UnaryUnion(ST_Collect(ST_Intersection(a.geom,b.geom))) AS geom
 FROM circles a JOIN circles b ON a.id < b.id AND a.geom && b.geom AND ST_Intersects(a.geom,b.geom))
SELECT ST_Area(CAST(v.geom AS geography)) AS boundary_m2,
 COALESCE(ST_Area(CAST(c.geom AS geography)),0) AS covered_m2,
 COALESCE(ST_Area(CAST(ST_CollectionExtract(o.geom,3) AS geography)),0) AS overlap_m2,
 ST_AsGeoJSON(v.geom) AS boundary_geojson,
 ST_AsGeoJSON(c.geom) AS covered_geojson,
 ST_AsGeoJSON(ST_CollectionExtract(o.geom,3)) AS overlap_geojson
FROM valid_boundary v CROSS JOIN covered c CROSS JOIN overlap o
""")


def coverage_area(db, boundary, resources, *, incomplete):
    result = {'algorithm_version': VERSION, 'state': 'unavailable',
        'boundary': '登记范围内的名义圆形覆盖，圆弧采用每四分之一圆32段近似；不表示视场、遮挡、道路或已验证防控效果。',
        'information_gaps': []}
    try:
        geometry, kind = _geometry(boundary)
    except ValueError as error:
        result['information_gaps'] = [str(error)]
        return result
    result['boundary_kind'] = kind
    if db.get_bind().dialect.name != 'postgresql':
        result['information_gaps'] = ['postgis_required_for_area_measurement']
        return result
    if len(resources) > 200:
        result['information_gaps'] = ['area_background_batch_required']
        return result
    values = []
    for row in resources:
        lon, lat, radius = row['longitude'], row['latitude'], row['coverage_radius_m']
        if (not all(type(value) in (int, float) and math.isfinite(value) for value in (lon, lat, radius))
                or not -180 <= lon <= 180 or not -85 <= lat <= 85 or not 0 < radius <= 10000):
            result['information_gaps'] = ['area_resource_invalid']
            return result
        values.append({'lon': lon, 'lat': lat, 'radius': radius})
    try:
        with db.begin_nested():
            previous = db.execute(text("SELECT current_setting('statement_timeout')")).scalar_one()
            db.execute(text("SELECT set_config('statement_timeout','5000',true)"))
            measured = db.execute(AREA_SQL, {'boundary': json.dumps(geometry), 'resources': json.dumps(values)}).mappings().first()
            db.execute(text("SELECT set_config('statement_timeout',:previous,true)"), {'previous': previous})
    except SQLAlchemyError:
        result['information_gaps'] = ['area_calculation_failed_or_timed_out']
        return result
    if measured is None or measured['boundary_m2'] <= 0:
        result['information_gaps'] = ['boundary_topology_invalid_or_empty']
        return result
    area, covered, overlap = (float(measured[key]) for key in ('boundary_m2', 'covered_m2', 'overlap_m2'))
    if not (all(math.isfinite(value) and value >= 0 for value in (area, covered, overlap))
            and covered <= area + 1 and overlap <= covered + 1):
        result['information_gaps'] = ['area_measurement_inconsistent']
        return result
    outside = max(0, area - covered)
    result.update(state='partial' if incomplete else 'calculated', boundary_area_m2=area,
        known_covered_area_m2=covered, unique_overlap_area_m2=overlap,
        outside_known_coverage_area_m2=outside, uncovered_area_m2=None if incomplete else outside)
    features = []
    for column, kind in [('boundary_geojson', 'registered_boundary'), ('covered_geojson', 'known_coverage'),
                         ('overlap_geojson', 'unique_overlap')]:
        if measured[column]:
            features.append({'type': 'Feature', 'properties': {'kind': kind}, 'geometry': json.loads(measured[column])})
    geometry = {'type': 'FeatureCollection', 'features': features}
    if len(json.dumps(geometry).encode()) <= 2_000_000:
        result['map_geometry'] = geometry
    else:
        result['information_gaps'].append('coverage_geometry_exceeds_interactive_budget')
    if incomplete:
        result['information_gaps'].append('resource_data_incomplete_not_a_confirmed_blind_area')
    return result
