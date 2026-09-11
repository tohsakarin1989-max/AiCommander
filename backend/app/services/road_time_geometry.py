"""Time-budget clipping of a native, edge-walk verified reference path.

This is a path prefix, not an exhaustive isochrone. End-node transition_time
belongs to entry into the NEXT edge and must not be spread along that edge.
"""
import math

from app.services.road_reachability_geometry import _slice_line, _distance
from app.services.vehicle_router import RoadCalculationError


def refine_timed_path(points, edges, seconds, measure):
    """Refine interpolation against native partial-edge costing, bounded work."""
    effective = seconds
    for attempt in range(5):
        result = clip_timed_path(points, edges, effective)
        features = result['features']
        if not features or not features[-1]['properties']['boundary_clipped']:
            result['properties']['time_budget_seconds'] = seconds
            return result
        measurement = measure(result)
        endpoint = None
        if isinstance(measurement, dict):
            measured = measurement.get('seconds')
            endpoint = measurement.get('endpoint')
            if (not isinstance(endpoint, list) or len(endpoint) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in endpoint)
                    or not -180 <= endpoint[0] <= 180 or not -85 <= endpoint[1] <= 85):
                raise RoadCalculationError('road_engine_response_invalid')
        else:
            measured = measurement
        if type(measured) not in (int, float) or not math.isfinite(measured) or measured < 0:
            raise RoadCalculationError('road_engine_response_invalid')
        if measured <= seconds:
            if isinstance(measurement, dict) and measurement.get('remove_terminal_sliver') is True:
                tail = features[-1]['geometry']['coordinates']
                if len(features) < 2 or sum(_distance(a, b) for a, b in zip(tail, tail[1:])) > 1:
                    raise RoadCalculationError('road_engine_response_invalid')
                features.pop()
                result['properties']['boundary_resolution_limited_m'] = 1.
            if endpoint is not None:
                # Publish the engine-verified endpoint, not a higher-precision
                # interpolation that native partial-edge costing did not use.
                features[-1]['geometry']['coordinates'][-1] = endpoint
            result['properties'].update(time_budget_seconds=seconds, boundary_verified_seconds=measured,
                                        boundary_refinement_steps=attempt)
            return result
        effective -= measured - seconds + .005
        if effective <= 0:
            break
    raise RoadCalculationError('road_engine_response_invalid')


def clip_timed_path(points, edges, seconds):
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 7200:
        raise ValueError('road_reachability_budget_invalid')
    try:
        if (not isinstance(points, list) or not 2 <= len(points) <= 100000
                or not isinstance(edges, list) or not 1 <= len(edges) <= 10000):
            raise ValueError('invalid path')
        for point in points:
            if (not isinstance(point, list) or len(point) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in point)
                    or not -180 <= point[0] <= 180 or not -85 <= point[1] <= 85):
                raise ValueError('invalid coordinates')
        prepared = []
        previous_index = 0
        elapsed = transition = 0.
        for edge in edges:
            begin, end = edge['begin_shape_index'], edge['end_shape_index']
            identifier = edge['id']
            node = edge['end_node']
            arrival, next_transition = node['elapsed_time'], node['transition_time']
            if (type(begin) is not int or type(end) is not int or begin != previous_index
                    or not 0 <= begin < end < len(points) or type(identifier) is not int or identifier < 0
                    or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
                           for v in (arrival, next_transition))):
                raise ValueError('invalid timed edge')
            departure = elapsed + transition
            if arrival <= departure:
                raise ValueError('non positive driving duration')
            prepared.append((identifier, begin, end, departure, arrival))
            previous_index, elapsed, transition = end, arrival, next_transition
        if previous_index != len(points) - 1 or transition != 0:
            raise ValueError('incomplete path')
        features = []
        for identifier, begin, end, departure, arrival in prepared:
            if seconds <= departure:
                break
            reached = min(seconds, arrival)
            fraction = (reached - departure) / (arrival - departure)
            line = points[begin:end + 1] if fraction == 1 else _slice_line(points[begin:end + 1], 0, fraction)
            features.append({'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': line},
                'properties': {'edge_id': identifier, 'departure_seconds': departure,
                    'arrival_seconds': reached, 'boundary_clipped': fraction < 1}})
        return {'type': 'FeatureCollection', 'features': features, 'properties': {
            'time_budget_seconds': seconds, 'path_duration_seconds': elapsed,
            'path_completed': seconds >= elapsed, 'coverage': 'reference_path_prefix_only',
            'time_basis': 'native_static_edge_and_transition_costs',
            'boundary_geometry': 'interpolated_not_surveyed'}}
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise RoadCalculationError('road_engine_response_invalid') from error
