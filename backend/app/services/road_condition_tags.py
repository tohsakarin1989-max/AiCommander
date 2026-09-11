"""Compile verified full-way internal conditions without weakening public limits.

Not an authorization API. The caller must freeze reviewed, permitted inputs.
Only exact full-way geometry correspondence is accepted; partial segments and
new junctions need the dedicated geometry compiler, not a nearest-road guess.
"""
import math
import re
import json

from app.services.road_access_policy import InternalRoadConditions


def _same_line(a, b):
    return len(a) == len(b) and all(
        len(left) == 2 and all(type(v) in (int, float) and math.isfinite(v) for v in left)
        and abs(left[0] - right[0]) <= 1e-7 and abs(left[1] - right[1]) <= 1e-7
        for left, right in zip(a, b))


def match_geometry_component(geometry, coordinates):
    """Return a unique full component and its orientation, never bridge gaps."""
    if geometry['type'] not in ('LineString', 'MultiLineString') or not isinstance(geometry['coordinates'], list):
        raise ValueError('road_overlay_full_geometry_required')
    lines = [geometry['coordinates']] if geometry['type'] == 'LineString' else geometry['coordinates']
    if not 1 <= len(lines) <= 10000:
        raise ValueError('road_overlay_full_geometry_required')
    if len(coordinates) < 2 or coordinates[0] == coordinates[-1]:
        raise ValueError('road_overlay_orientation_unresolved')
    matches = []
    for index, line in enumerate(lines):
        if not isinstance(line, list) or len(line) < 2 or any(
                not isinstance(point, list) or len(point) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in point)
                or not -180 <= point[0] <= 180 or not -85 <= point[1] <= 85 for point in line):
            raise ValueError('road_overlay_full_geometry_required')
        if _same_line(line, coordinates):
            matches.append((index, False, len(lines)))
        elif _same_line(line, list(reversed(coordinates))):
            matches.append((index, True, len(lines)))
    if len(matches) != 1:
        raise ValueError('road_overlay_full_geometry_required')
    return matches[0]


def compile_condition_tags(tags, coordinates, overlay):
    _, reverse, _ = match_geometry_component(overlay['geometry'], coordinates)
    conditions = InternalRoadConditions.model_validate_json(json.dumps(overlay['conditions']))
    if conditions.gate != 'open' or conditions.access != 'permitted' or conditions.direction == 'unknown':
        raise ValueError('road_overlay_not_permitted')
    direction = conditions.direction
    if reverse and direction != 'both':
        direction = 'reverse' if direction == 'forward' else 'forward'
    output = dict(tags)
    if direction != 'both':
        allowed = {'forward', 'reverse'}
        direction_tags = ['oneway', 'oneway:vehicle', 'oneway:motor_vehicle', 'oneway:motorcar', 'oneway:hgv']
        if output.get('junction') == 'roundabout' and 'oneway' not in output:
            raise ValueError('road_overlay_public_direction_unresolved')
        for key in direction_tags:
            value = output.get(key)
            if value is None:
                continue
            if value in ('yes', '1', 'true'):
                allowed.intersection_update({'forward'})
            elif value in ('-1', 'reverse'):
                allowed.intersection_update({'reverse'})
            elif value not in ('no', '0', 'false'):
                raise ValueError('road_overlay_public_direction_unresolved')
        if any(key.startswith('oneway') and 'conditional' in key for key in output):
            raise ValueError('road_overlay_public_direction_unresolved')
        if direction not in allowed:
            raise ValueError('road_overlay_direction_conflict')
        # Explicit mode tags must not override the new generic restriction.
        for key in direction_tags:
            if key == 'oneway' or key in output:
                output[key] = 'yes' if direction == 'forward' else '-1'
    for key, limit, unit in [('maxheight', conditions.max_height_m, 'm'), ('maxweight', conditions.max_weight_t, 't')]:
        if limit is None:
            continue
        previous = output.get(key)
        if previous is not None:
            match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*' + unit + '?', previous.strip())
            if not match or float(match[1]) <= 0:
                raise ValueError('road_overlay_public_limit_unresolved')
            limit = min(limit, float(match[1]))
        # Directional/mode-specific/conditional limits need their own merge;
        # a more specific tag could otherwise override the new generic limit.
        if any(name.startswith(key + ':') for name in output):
            raise ValueError('road_overlay_public_limit_unresolved')
        output[key] = format(limit, '.12g')
    return output
