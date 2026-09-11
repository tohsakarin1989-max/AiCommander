"""Reconstruct directed native expansion branches for exact edge-walk costing.

No nearest-road matching or routing is used to repair a broken predecessor
chain. A valid set of branches does not prove the debug expansion is complete.
"""
import math

from app.services.road_reachability_geometry import INVALID_EDGE_ID, _slice_line, _distance
from app.services.vehicle_router import RoadCalculationError


def trace_shape(points):
    """Densify only existing line segments so edge_walk cannot cut corners."""
    output = []
    for start, end in zip(points, points[1:]):
        steps = max(1, math.ceil(_distance(start, end) / 20))
        if len(output) + steps > 10000:
            raise RoadCalculationError('road_calculation_capacity_exceeded')
        for index in range(steps):
            ratio = index / steps
            output.append({'lon': start[0] + (end[0] - start[0]) * ratio,
                           'lat': start[1] + (end[1] - start[1]) * ratio,
                           'node_snap_tolerance': 0, 'radius': 1, 'search_cutoff': 1})
    output.append({'lon': points[-1][0], 'lat': points[-1][1],
                   'node_snap_tolerance': 0, 'radius': 1, 'search_cutoff': 1})
    return output


def time_expansion_paths(raw, seeds, seconds):
    """Materialized compatibility helper for small tests and diagnostics."""
    return list(iter_time_expansion_paths(raw, seeds, seconds))


def iter_time_expansion_paths(raw, seeds, seconds):
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 7200:
        raise ValueError('road_reachability_budget_invalid')
    try:
        if (raw['type'] != 'FeatureCollection' or raw['properties']['algorithm'] != 'dijkstras'
                or not isinstance(raw['features'], list) or not 1 <= len(raw['features']) <= 10000):
            raise ValueError('invalid expansion')
        nodes = {}
        for feature in raw['features']:
            prop = feature['properties']
            if prop['edge_status'] != 's':
                continue
            identifier, parent, duration = prop['edge_id'], prop['pred_edge_id'], prop['duration']
            points = feature['geometry']['coordinates']
            if (type(identifier) is not int or not 0 <= identifier < INVALID_EDGE_ID
                    or identifier in nodes or type(parent) is not int or not 0 <= parent <= INVALID_EDGE_ID
                    or type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0
                    or prop['expansion_type'] != 0 or feature['geometry']['type'] != 'LineString'
                    or not isinstance(points, list) or not 2 <= len(points) <= 10000):
                raise ValueError('invalid edge')
            for point in points:
                if (not isinstance(point, list) or len(point) != 2
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in point)
                        or not -180 <= point[0] <= 180 or not -85 <= point[1] <= 85):
                    raise ValueError('invalid point')
            nodes[identifier] = (parent, duration, points)
        retained = {}
        for identifier, (parent, duration, points) in nodes.items():
            if parent == INVALID_EDGE_ID:
                fraction = seeds[identifier]
                if type(fraction) not in (int, float) or not math.isfinite(fraction) or not 0 <= fraction < 1:
                    raise ValueError('invalid seed')
                points = _slice_line(points, fraction, 1)
            elif nodes[parent][1] > seconds + 1:
                # Expansion emits whole frontier edges. Rounded cumulative
                # seconds only select a superset; final clipping uses trace.
                continue
            retained[identifier] = (parent, points)
        leaves = sorted(set(retained) - {value[0] for value in retained.values()})
        if len(leaves) > 4096:
            raise RoadCalculationError('road_calculation_capacity_exceeded')
        if not leaves:
            raise ValueError('no rooted branches')
        visited, total_points = set(), 0
        for leaf in leaves:
            identifiers, local = [], set()
            current = leaf
            while current != INVALID_EDGE_ID:
                if current in local:
                    raise ValueError('predecessor cycle')
                local.add(current)
                identifiers.append(current)
                current = retained[current][0]
            identifiers.reverse()
            points = []
            for identifier in identifiers:
                segment = retained[identifier][1]
                if points and points[-1] != segment[0]:
                    raise ValueError('disconnected geometry')
                points.extend(segment if not points else segment[1:])
            total_points += len(points)
            if total_points > 1000000:
                raise RoadCalculationError('road_calculation_capacity_exceeded')
            visited.update(local)
            # Only one reconstructed branch is held at a time. The cumulative
            # work limit still bounds repeated prefix costing across leaves.
            yield {'edge_ids': identifiers, 'points': points}
        if visited != set(retained):
            raise ValueError('unrooted component')
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise RoadCalculationError('road_engine_response_invalid') from error
