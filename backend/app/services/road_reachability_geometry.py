"""Render distance-budget expansion as directed road segments, never area fill.

Valhalla expansion includes frontier edges beyond the contour and complete seed
edges. This helper clips those geometries. Distances remain engine measures;
interpolated boundary coordinates are not surveyed positions or entrance proof.
Time-budget clipping needs transition-cost accounting and is not implemented here.
"""
import math

from app.services.vehicle_router import RoadCalculationError


INVALID_EDGE_ID = 70368744177663


def _distance(a, b):
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2)
         * math.sin(math.radians(b[0] - a[0]) / 2) ** 2)
    return 12742017.6 * math.asin(math.sqrt(min(1., max(0., h))))


def _slice_line(points, start_fraction, end_fraction):
    lengths = [_distance(a, b) for a, b in zip(points, points[1:])]
    total = sum(lengths)
    if total <= 0:
        raise ValueError('zero length geometry')
    lower, upper = total * start_fraction, total * end_fraction
    result, position = [], 0.
    for a, b, length in zip(points, points[1:], lengths):
        if length > 0 and position < upper and position + length > lower:
            left = max(0., (lower - position) / length)
            right = min(1., (upper - position) / length)
            for fraction in (left, right):
                point = [a[0] + (b[0] - a[0]) * fraction,
                         a[1] + (b[1] - a[1]) * fraction]
                if not result or result[-1] != point:
                    result.append(point)
        position += length
    return result


def clip_distance_expansion(raw, seed_percent_along, distance_m):
    """Clip settled forward edges using their cumulative engine distances.

seed_percent_along maps directed graph edge IDs to locate's percent_along,
not way IDs or a nearest-line guess. Call only with the same graph/vehicle and
origin used by expansion. Caller owns graph authorization and process budgets.
"""
    if type(distance_m) not in (int, float) or not math.isfinite(distance_m) or not 0 < distance_m <= 50000:
        raise ValueError('road_reachability_budget_invalid')
    try:
        if raw['type'] != 'FeatureCollection' or raw['properties']['algorithm'] != 'dijkstras':
            raise ValueError('unexpected expansion')
        features = raw['features']
        if not isinstance(features, list) or len(features) > 10000:
            raise ValueError('expansion size')
        if (not isinstance(seed_percent_along, dict) or not seed_percent_along
                or any(type(key) is not int or key < 0
                       or type(value) not in (int, float) or not math.isfinite(value)
                       or not 0 <= value <= 1 for key, value in seed_percent_along.items())):
            raise ValueError('seed correlations')
        settled = {}
        for feature in features:
            properties = feature['properties']
            if properties['edge_status'] != 's':
                continue
            edge_id, predecessor = properties['edge_id'], properties['pred_edge_id']
            end = properties['distance']
            if (type(edge_id) is not int or edge_id < 0 or edge_id == INVALID_EDGE_ID
                    or edge_id in settled or type(predecessor) is not int or predecessor < 0
                    or properties['expansion_type'] != 0
                    or type(end) not in (int, float) or not math.isfinite(end) or end < 0):
                raise ValueError('invalid directed expansion edge')
            geometry = feature['geometry']
            points = geometry['coordinates']
            if (geometry['type'] != 'LineString' or not isinstance(points, list)
                    or not 2 <= len(points) <= 10000):
                raise ValueError('invalid edge geometry')
            for point in points:
                if (not isinstance(point, list) or len(point) != 2
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in point)
                        or not -180 <= point[0] <= 180 or not -85 <= point[1] <= 85):
                    raise ValueError('invalid coordinate')
            settled[edge_id] = (predecessor, end, points)
        output = []
        for edge_id, (predecessor, end, points) in settled.items():
            if predecessor == INVALID_EDGE_ID:
                start, fraction = 0., seed_percent_along[edge_id]
            else:
                start, fraction = settled[predecessor][1], 0.
            if end < start or (end == start and fraction < 1):
                raise ValueError('non increasing distance')
            if start >= distance_m or end == start or fraction == 1:
                continue
            reached = min(end, distance_m)
            upper = fraction + (1 - fraction) * (reached - start) / (end - start)
            line = _slice_line(points, fraction, upper)
            if len(line) < 2:
                raise ValueError('empty clipped edge')
            output.append({'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': line},
                           'properties': {'edge_id': edge_id, 'start_distance_m': start,
                                          'end_distance_m': reached, 'boundary_clipped': end > distance_m,
                                          'seed_clipped': fraction > 0}})
        return {'type': 'FeatureCollection', 'features': output,
                'properties': {'distance_budget_m': distance_m,
                               'distance_basis': 'engine_accumulated_road_length',
                               'boundary_geometry': 'interpolated_not_surveyed',
                               'coverage': 'directed_expansion_not_area_coverage'}}
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise RoadCalculationError('road_engine_response_invalid') from error
