"""Private, offline Valhalla adapter; never accepts arbitrary engine JSON.

Callers must supply a verified immutable eligible graph and re-authorize before
delivery. This adapter alone is not the public routing authorization boundary.
Run native calls in a disposable worker process to enforce wall-clock budgets.
"""
import importlib.metadata
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.services.road_access_policy import VehicleAssumption


ENGINE_VERSION = '3.8.3'
SNAP_LIMIT_METERS = 30.0


class RoadCalculationError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class RoadLocation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-85, le=85, allow_inf_nan=False)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _native_completion_contract(raw):
    """Read execution evidence without conflating it with coverage acceptance."""
    properties = raw.get('properties') if isinstance(raw, dict) else None
    if not isinstance(properties, dict):
        raise RoadCalculationError('road_engine_response_invalid')
    marker = properties.get('aicommander_expansion_contract')
    if marker is not None and marker != 'completed-v1':
        raise RoadCalculationError('road_engine_response_invalid')
    return marker


class VehicleRouter:
    def __init__(self, tiles: Path):
        # Optional dependency: importing core business services never loads it.
        if importlib.metadata.version('pyvalhalla') != ENGINE_VERSION:
            raise RoadCalculationError('road_engine_version_mismatch')
        from valhalla import Actor
        from valhalla.config import get_config
        config = get_config(tile_dir=str(tiles), tile_extract='')
        config['mjolnir'].update(tile_dir=str(tiles), tile_extract='', tile_url='',
                                 traffic_extract='', admin='', timezone='')
        self._actor = Actor(config)

    def _call(self, method, payload):
        try:
            return getattr(self._actor, method)(payload)
        except Exception as error:
            # Native text may contain coordinates/config paths; do not expose it.
            # Failure is not proof of no connection or an impossible journey.
            raise RoadCalculationError('road_engine_calculation_failed') from error

    def _prepare(self, points, vehicle: VehicleAssumption, *, include_directed_seeds=False,
                 shortest_distance=False):
        if vehicle.kind == 'truck' and (vehicle.height_m is None or vehicle.weight_t is None):
            raise RoadCalculationError('road_vehicle_dimensions_missing')
        options = {}
        if shortest_distance:
            # Server-owned search objective; this never relaxes access rules.
            options['shortest'] = True
        if vehicle.kind == 'truck':
            options.update(height=vehicle.height_m, weight=vehicle.weight_t)
        payload = {'costing': vehicle.kind, 'units': 'kilometers',
                   'costing_options': {vehicle.kind: options}}
        locations = [{'lon': point.longitude, 'lat': point.latitude,
                      'radius': SNAP_LIMIT_METERS, 'search_cutoff': SNAP_LIMIT_METERS,
                      'node_snap_tolerance': 0, 'minimum_reachability': 0}
                     for point in points]
        correlations = []
        for location in locations:
            result = self._call('locate', {**payload, 'locations': [location], 'verbose': True})
            if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
                raise RoadCalculationError('road_engine_response_invalid')
            edges = result[0].get('edges')
            if not isinstance(edges, list) or not edges:
                raise RoadCalculationError('road_location_connection_unverified')
            ways = set()
            distances = []
            for edge in edges:
                distance = edge.get('distance') if isinstance(edge, dict) else None
                info = edge.get('edge_info') if isinstance(edge, dict) else None
                way = info.get('way_id') if isinstance(info, dict) else None
                if not _number(distance) or distance > SNAP_LIMIT_METERS or type(way) is not int or way <= 0:
                    raise RoadCalculationError('road_location_connection_unverified')
                ways.add(way)
                distances.append(distance)
            correlation = {'way_ids': sorted(ways), 'maximum_distance_m': max(distances)}
            if include_directed_seeds:
                seeds = {}
                for edge in edges:
                    identifier = edge.get('edge_id')
                    identifier = identifier.get('value') if isinstance(identifier, dict) else None
                    fraction = edge.get('percent_along')
                    if (type(identifier) is not int or not 0 <= identifier < 70368744177663
                            or identifier in seeds or not _number(fraction) or fraction > 1):
                        raise RoadCalculationError('road_location_connection_unverified')
                    seeds[identifier] = fraction
                correlation['directed_seeds'] = seeds
            correlations.append(correlation)
        return payload, locations, correlations

    def distance_reachability(self, origin: RoadLocation, vehicle: VehicleAssumption, distance_m):
        # Local import avoids making route/matrix depend on expansion parsing.
        from app.services.road_reachability_geometry import clip_distance_expansion
        if not _number(distance_m) or not 0 < distance_m <= 50000:
            raise ValueError('road_reachability_budget_invalid')
        payload, locations, correlations = self._prepare(
            [origin], vehicle, include_directed_seeds=True, shortest_distance=True)
        seeds = correlations[0].pop('directed_seeds')
        contour_request = {**payload, 'locations': locations, 'generalize': 0,
                           'contours': [{'distance': distance_m / 1000}]}
        # The native expansion action catches underlying exceptions and can
        # serialize a partial trace. Its GeoJSON is not a success signal.
        # A direct isochrone call surfaces deterministic costing/graph errors;
        # it still does not prove a later expansion trace is exhaustive.
        contour = self._call('isochrone', {**contour_request, 'polygons': False})
        try:
            if (contour['type'] != 'FeatureCollection' or not isinstance(contour['features'], list)
                    or not contour['features'] or len(contour['features']) > 10000):
                raise ValueError('invalid contour response')
            for feature in contour['features']:
                properties = feature['properties']
                value = properties['contour']
                if (properties['metric'] != 'distance' or not _number(value)
                        or not math.isclose(value, distance_m / 1000, abs_tol=1e-6)):
                    raise ValueError('wrong contour budget')
                geometry = feature['geometry']
                if geometry['type'] not in ('LineString', 'MultiLineString') or not geometry['coordinates']:
                    raise ValueError('missing contour geometry')
        except (KeyError, TypeError, ValueError) as error:
            raise RoadCalculationError('road_engine_response_invalid') from error
        raw = self._call('expansion', {**payload, 'action': 'isochrone', 'locations': locations,
            # Expansion otherwise simplifies geometry by 10m, moving boundary
            # interpolation off the actual road (verified on the frozen graph).
            'generalize': 0, 'contours': [{'distance': distance_m / 1000}],
            'dedupe': True, 'skip_opposites': False,
            'expansion_properties': ['distance', 'edge_id', 'pred_edge_id', 'edge_status', 'expansion_type']})
        geometry = clip_distance_expansion(raw, seeds, distance_m)
        native_contract = _native_completion_contract(raw)
        return {'schema_version': 'vehicle-distance-reachability-4.2.0-2',
                'search_objective': 'shortest_road_distance',
                'engine_version': ENGINE_VERSION, 'distance_budget_m': distance_m,
                'status': 'partial_reference',
                'native_completion_contract': native_contract,
                'completion': {'budget_calculation': 'completed', 'road_expansion': 'unverified'},
                'roads': geometry, 'correlations': correlations, 'vehicle': vehicle.model_dump(),
                'limitations': ['directed_expansion_not_area_coverage',
                                'expansion_completeness_not_confirmed',
                                'boundary_interpolated_not_surveyed',
                                'outside_result_not_proof_of_unreachability',
                                'unprovided_vehicle_attributes_use_engine_defaults',
                                'snapping_not_verified_facility_entrance']}

    def route(self, start: RoadLocation, end: RoadLocation, vehicle: VehicleAssumption):
        payload, locations, correlations = self._prepare((start, end), vehicle)
        # Same eligible graph and hard restrictions for every path. Not exposed
        # as an arbitrary engine option; bound native work to one alternative.
        raw = self._call('route', {**payload, 'locations': locations, 'alternates': 1})
        primary = self._validated_path(raw, payload, correlations)
        alternates = raw.get('alternates', [])
        if not isinstance(alternates, list) or len(alternates) > 1:
            raise RoadCalculationError('road_engine_response_invalid')
        alternatives = []
        for candidate in alternates:
            alternate = self._validated_path(candidate, payload, correlations)
            # Identical shapes or identical road sequences are not a useful
            # separate corridor. Do not advertise native duplicates as choices.
            if (alternate['shape_polyline6'] != primary['shape_polyline6']
                    and alternate['way_ids'] != primary['way_ids']):
                alternatives.append(alternate)
        return {'schema_version': 'vehicle-route-4.2.0-1', 'engine_version': ENGINE_VERSION,
                **primary, 'alternatives': alternatives,
                'alternatives_status': 'available' if alternatives else 'no_distinct_alternative_returned',
                'correlations': correlations,
                'vehicle': vehicle.model_dump(), 'time_basis': 'valhalla_static_road_speed_assumptions',
                'limitations': ['reference_path_not_observed_trajectory',
                                'alternatives_are_not_all_possible_routes',
                                'unprovided_vehicle_attributes_use_engine_defaults',
                                'snapping_not_verified_facility_entrance']}

    def _validated_path(self, raw, payload, correlations):
        from app.services.road_polyline import decode_road_geometry
        from app.services.road_detour import detour_reference
        try:
            trip = raw['trip']
            distance = trip['summary']['length']
            seconds = trip['summary']['time']
            legs = trip['legs']
            if trip['status'] != 0 or trip['units'] != 'kilometers' or len(legs) != 1:
                raise ValueError('unexpected trip')
            if not _number(distance) or not _number(seconds):
                raise ValueError('invalid measures')
            encoded = legs[0]['shape']
            if not isinstance(encoded, str) or not encoded or len(encoded) > 2_000_000:
                raise ValueError('invalid shape')
            detour = detour_reference(decode_road_geometry(encoded), distance * 1000)
        except (KeyError, TypeError, ValueError) as error:
            raise RoadCalculationError('road_engine_response_invalid') from error
        trace = self._call('trace_attributes', {**payload, 'encoded_polyline': encoded,
            'shape_match': 'edge_walk', 'filters': {'action': 'include', 'attributes': ['edge.way_id']}})
        try:
            ways = [edge['way_id'] for edge in trace['edges']]
            if not ways or any(type(way) is not int or way <= 0 for way in ways):
                raise ValueError('invalid path references')
            if ways[0] not in correlations[0]['way_ids'] or ways[-1] not in correlations[1]['way_ids']:
                raise ValueError('different endpoint roads')
        except (KeyError, TypeError, ValueError) as error:
            raise RoadCalculationError('road_route_connection_unverified') from error
        return {'distance_m': distance * 1000, 'reference_time_seconds': seconds,
                'shape_polyline6': encoded, 'way_ids': ways, 'detour_reference': detour}

    def time_reachability(self, origin, vehicle, seconds):
        """Time-costed native branches; debug expansion completeness is explicit."""
        if not _number(seconds) or not 0 < seconds <= 7200:
            raise ValueError('road_reachability_budget_invalid')
        from app.services.road_polyline import decode_road_geometry
        from app.services.road_expansion_paths import iter_time_expansion_paths, trace_shape
        from app.services.road_time_geometry import refine_timed_path
        payload, locations, correlations = self._prepare([origin], vehicle, include_directed_seeds=True)
        seeds = correlations[0].pop('directed_seeds')
        contour_request = {**payload, 'locations': locations, 'generalize': 0,
                           'contours': [{'time': seconds / 60}]}
        contour = self._call('isochrone', {**contour_request, 'polygons': False})
        try:
            if (contour['type'] != 'FeatureCollection' or not isinstance(contour['features'], list)
                    or not 1 <= len(contour['features']) <= 10000):
                raise ValueError('invalid contour')
            for feature in contour['features']:
                if (feature['properties']['metric'] != 'time'
                        or not _number(feature['properties']['contour'])
                        or not math.isclose(feature['properties']['contour'], seconds / 60, abs_tol=1e-6)
                        or feature['geometry']['type'] not in ('LineString', 'MultiLineString')
                        or not feature['geometry']['coordinates']):
                    raise ValueError('invalid time contour')
            raw = self._call('expansion', {**contour_request, 'action': 'isochrone',
                'dedupe': True, 'skip_opposites': False, 'expansion_properties': [
                    'duration', 'edge_id', 'pred_edge_id', 'edge_status', 'expansion_type']})
            paths = iter_time_expansion_paths(raw, seeds, seconds)
            native_contract = _native_completion_contract(raw)
            features, seen, branches = [], {}, []
            trace_methods = {'edge_walk': 0, 'map_snap_verified': 0}
            for path in paths:
                trace = self._call('trace_attributes', {**payload,
                    # Use graph geometry as-is. Default node snapping can move
                    # a short edge's endpoint back to the previous junction.
                    'shape': [{'lon': x, 'lat': y, 'node_snap_tolerance': 0,
                               'radius': 1, 'search_cutoff': 1} for x, y in path['points']],
                    'shape_match': 'edge_walk',
                    'filters': {'action': 'include', 'attributes': ['shape', 'edge.id',
                        'edge.begin_shape_index', 'edge.end_shape_index', 'node.elapsed_time', 'node.transition_time']}})
                expected = path['edge_ids']
                method = 'edge_walk'
                if [edge['id'] for edge in trace['edges'][:len(expected)]] != expected:
                    # Sparse corner geometry can be interpreted as a shortcut
                    # by edge_walk. Re-cost a dense trace only if EVERY directed
                    # edge still matches the original expansion. Never accept
                    # a nearby or newly routed substitute branch.
                    trace = self._call('trace_attributes', {**payload, 'shape': trace_shape(path['points']),
                        'shape_match': 'map_snap', 'filters': {'action': 'include', 'attributes': [
                            'shape', 'edge.id', 'edge.begin_shape_index', 'edge.end_shape_index',
                            'node.elapsed_time', 'node.transition_time']}})
                    method = 'map_snap_verified'
                if (trace['units'] != 'kilometers'
                        or [edge['id'] for edge in trace['edges'][:len(expected)]] != expected):
                    raise ValueError('different expansion path')
                points = decode_road_geometry(trace['shape'])
                edges = trace['edges'][:len(expected)]
                last_index = edges[-1]['end_shape_index']
                # Both interfaces quantize to 1e-6 degrees, with differing
                # rounding at some native node coordinates. IDs still match.
                if any(abs(a - b) > 1.01e-6 for a, b in zip(points[last_index], path['points'][-1])):
                    raise ValueError('different expansion endpoint')
                # At an exact junction edge_walk can append a tiny following
                # edge. Stop at the proven requested node, never include that
                # extra edge or charge its turn. All requested IDs must match.
                edges[-1] = {**edges[-1], 'end_node': {**edges[-1]['end_node'], 'transition_time': 0.}}
                clipped = refine_timed_path(points[:last_index + 1], edges, seconds,
                                           lambda candidate: self._measure_time_boundary(payload, candidate))
                trace_methods[method] += 1
                parent_index = None
                for feature in clipped['features']:
                    # Shared prefixes appear in multiple leaf paths. Remove
                    # exact duplicates, never conflate different approaches.
                    key = (parent_index, feature['properties']['edge_id'], feature['properties']['departure_seconds'],
                           feature['properties']['arrival_seconds'],
                           tuple(tuple(point) for point in feature['geometry']['coordinates']))
                    if key not in seen:
                        seen[key] = len(features)
                        feature['properties']['parent_feature_index'] = parent_index
                        features.append(feature)
                    parent_index = seen[key]
                branches.append({'source_leaf_edge_id': expected[-1], 'tip_feature_index': parent_index,
                                 'trace_method': method,
                                 'boundary_verified_seconds': clipped['properties'].get('boundary_verified_seconds'),
                                 'boundary_resolution_limited_m': clipped['properties'].get('boundary_resolution_limited_m'),
                                 'boundary_refinement_steps': clipped['properties'].get('boundary_refinement_steps', 0)})
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise RoadCalculationError('road_engine_response_invalid') from error
        return {'schema_version': 'vehicle-time-reachability-4.2.0-1', 'engine_version': ENGINE_VERSION,
                'time_budget_seconds': seconds, 'status': 'partial_reference',
                'native_completion_contract': native_contract,
                'completion': {'branch_timing': 'native_path_ids_verified', 'road_expansion': 'unverified'},
                'trace_methods': trace_methods,
                'branches': branches, 'branch_reference_schema': 'shared-prefix-1',
                'roads': {'type': 'FeatureCollection', 'features': features},
                'correlations': correlations, 'vehicle': vehicle.model_dump(), 'branch_count': len(branches),
                'limitations': ['expansion_completeness_not_confirmed', 'outside_result_not_proof_of_unreachability',
                                'boundary_interpolated_not_surveyed', 'static_road_speed_and_transition_assumptions',
                                'snapping_not_verified_facility_entrance']}

    def _measure_time_boundary(self, payload, clipped):
        from app.services.road_expansion_paths import trace_shape
        from app.services.road_polyline import decode_road_geometry
        from app.services.road_reachability_geometry import _distance
        features = clipped['features']
        points = []
        for feature in features:
            points.extend(feature['geometry']['coordinates'] if not points else feature['geometry']['coordinates'][1:])
        expected = [feature['properties']['edge_id'] for feature in features]
        shapes = [('edge_walk', [{'lon': x, 'lat': y, 'node_snap_tolerance': 0,
                                 'radius': 1, 'search_cutoff': 1} for x, y in points]),
                  ('map_snap', trace_shape(points))]
        for method, shape in shapes:
            try:
                trace = self._call('trace_attributes', {**payload, 'shape': shape, 'shape_match': method,
                    'filters': {'action': 'include', 'attributes': [
                        'shape', 'edge.id', 'edge.end_shape_index', 'node.elapsed_time']}})
                actual = [edge['id'] for edge in trace['edges']]
                decoded = decode_road_geometry(trace['shape'])
                if actual[:len(expected)] == expected:
                    end = trace['edges'][len(expected) - 1]
                    coordinate = decoded[end['end_shape_index']]
                    if _distance(coordinate, points[-1]) <= 1.:
                        # Cost and geometry must refer to the SAME native
                        # endpoint. Keep exact edge IDs and the 1m correlation
                        # limit, then return that point for final publication.
                        return {'seconds': end['end_node']['elapsed_time'], 'endpoint': coordinate}
                elif actual == expected[:-1]:
                    tail = features[-1]
                    coordinates = tail['geometry']['coordinates']
                    # If native matching cannot resolve a sub-metre terminal
                    # sliver, return the last proven node, explicitly marked
                    # resolution-limited. Do not invent the missing turn cost.
                    if (len(features) > 1 and sum(_distance(a, b) for a, b in zip(coordinates, coordinates[1:])) <= 1
                            and all(abs(a - b) <= 1.01e-6 for a, b in zip(decoded[-1], coordinates[0]))):
                        return {'seconds': trace['edges'][-1]['end_node']['elapsed_time'],
                                'endpoint': decoded[-1], 'remove_terminal_sliver': True}
            except (RoadCalculationError, KeyError, TypeError, ValueError, IndexError):
                continue
        raise RoadCalculationError('road_engine_response_invalid')

    def route_time_prefix(self, start, end, vehicle, seconds):
        """Private primitive for time-bound reference paths, not full coverage."""
        if not _number(seconds) or not 0 < seconds <= 7200:
            raise ValueError('road_reachability_budget_invalid')
        from app.services.road_polyline import decode_road_geometry
        from app.services.road_time_geometry import refine_timed_path
        route = self.route(start, end, vehicle)
        options = {} if vehicle.kind == 'auto' else {'height': vehicle.height_m, 'weight': vehicle.weight_t}
        trace = self._call('trace_attributes', {'costing': vehicle.kind, 'units': 'kilometers',
            'costing_options': {vehicle.kind: options}, 'encoded_polyline': route['shape_polyline6'],
            'shape_match': 'edge_walk', 'filters': {'action': 'include', 'attributes': [
                'shape', 'edge.id', 'edge.way_id', 'edge.begin_shape_index', 'edge.end_shape_index',
                'node.elapsed_time', 'node.transition_time']}})
        try:
            if (trace['units'] != 'kilometers' or trace['shape'] != route['shape_polyline6']
                    or [edge['way_id'] for edge in trace['edges']] != route['way_ids']
                    or abs(trace['edges'][-1]['end_node']['elapsed_time'] - route['reference_time_seconds']) > .01):
                raise ValueError('different timed path')
            roads = refine_timed_path(decode_road_geometry(trace['shape']), trace['edges'], seconds,
                lambda candidate: self._measure_time_boundary({'costing': vehicle.kind, 'units': 'kilometers',
                    'costing_options': {vehicle.kind: options}}, candidate))
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise RoadCalculationError('road_engine_response_invalid') from error
        return {'schema_version': 'vehicle-time-path-4.2.0-1', 'engine_version': ENGINE_VERSION,
                'roads': roads, 'vehicle': vehicle.model_dump(), 'correlations': route['correlations'],
                'limitations': [*route['limitations'], 'reference_path_prefix_not_complete_reachable_network']}

    def matrix(self, sources: list[RoadLocation], targets: list[RoadLocation], vehicle: VehicleAssumption):
        if not 1 <= len(sources) <= 10 or not 1 <= len(targets) <= 10:
            raise ValueError('road_matrix_size_invalid')
        payload, locations, correlations = self._prepare([*sources, *targets], vehicle)
        raw = self._call('matrix', {**payload, 'sources': locations[:len(sources)],
                                   'targets': locations[len(sources):], 'verbose': True})
        try:
            rows = raw['sources_to_targets']
            if raw['units'] != 'kilometers' or len(rows) != len(sources):
                raise ValueError('matrix shape or units')
            cells = []
            for i, row in enumerate(rows):
                if not isinstance(row, list) or len(row) != len(targets):
                    raise ValueError('matrix dimensions')
                for j, cell in enumerate(row):
                    if (type(cell['from_index']) is not int or type(cell['to_index']) is not int
                            or cell['from_index'] != i or cell['to_index'] != j):
                        raise ValueError('matrix order')
                    distance, seconds = cell['distance'], cell['time']
                    if distance is None and seconds is None:
                        cells.append({'source_index': i, 'target_index': j, 'status': 'no_path_found',
                                      'distance_m': None, 'reference_time_seconds': None})
                        continue
                    if not _number(distance) or not _number(seconds):
                        raise ValueError('matrix measures')
                    for prefix, point in (('begin', sources[i]), ('end', targets[j])):
                        lat, lon = cell[f'{prefix}_lat'], cell[f'{prefix}_lon']
                        if (type(lat) not in (float, int) or type(lon) not in (float, int)
                                or not math.isfinite(lat) or not math.isfinite(lon)
                                or not -90 <= lat <= 90 or not -180 <= lon <= 180):
                            raise ValueError('matrix correlation')
                        dlat = math.radians(lat - point.latitude)
                        dlon = math.radians(lon - point.longitude)
                        a = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat))
                             * math.cos(math.radians(point.latitude)) * math.sin(dlon / 2) ** 2)
                        if 6371008.8 * 2 * math.asin(math.sqrt(min(1., max(0., a)))) > SNAP_LIMIT_METERS:
                            raise ValueError('matrix endpoint too far')
                    cells.append({'source_index': i, 'target_index': j, 'status': 'calculated',
                                  'distance_m': distance * 1000, 'reference_time_seconds': seconds})
        except (KeyError, TypeError, ValueError) as error:
            raise RoadCalculationError('road_engine_response_invalid') from error
        return {'schema_version': 'vehicle-matrix-4.2.0-1', 'engine_version': ENGINE_VERSION,
                'source_count': len(sources), 'target_count': len(targets), 'cells': cells,
                'source_correlations': correlations[:len(sources)],
                'target_correlations': correlations[len(sources):], 'vehicle': vehicle.model_dump(),
                'time_basis': 'valhalla_static_road_speed_assumptions',
                'limitations': ['directional_road_distances_not_symmetric',
                                'no_path_found_not_proof_of_physical_impossibility',
                                'unprovided_vehicle_attributes_use_engine_defaults',
                                'snapping_not_verified_facility_entrance']}
