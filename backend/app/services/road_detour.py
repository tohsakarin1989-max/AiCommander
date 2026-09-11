"""Reference detour relative to the actual route endpoints, not facility centres."""
import math


def detour_reference(points, road_distance_m):
    start, end = points[0], points[-1]
    lat1, lat2 = math.radians(start[1]), math.radians(end[1])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(math.radians(end[0] - start[0]) / 2) ** 2)
    straight = 12742017.6 * math.asin(math.sqrt(min(1., max(0., h))))
    if (type(road_distance_m) not in (int, float) or not math.isfinite(road_distance_m)
            or road_distance_m < 0 or not math.isfinite(straight)):
        raise ValueError('road_detour_measure_invalid')
    result = {'basis': 'route_geometry_endpoints', 'straight_distance_m': straight,
              'road_distance_m': road_distance_m, 'ratio': None, 'additional_distance_m': None}
    if straight < 10:
        return {**result, 'status': 'endpoints_too_close'}
    if road_distance_m < straight:
        if straight - road_distance_m > max(5., straight * .01):
            raise ValueError('road_detour_measure_inconsistent')
        return {**result, 'status': 'rounding_limited'}
    return {**result, 'status': 'available', 'ratio': road_distance_m / straight,
            'additional_distance_m': road_distance_m - straight}
