"""Public way access policy for an unprivileged reference vehicle.

OSM mode-specific access overrides generic access. Destination/customer/private
permissions are not inferred from a routing endpoint. Conditional/directional
access is reported as unresolved until its dedicated compiler is available.
"""
POLICY_VERSION = 'public-way-access-4.2.0-1'
NODE_POLICY_VERSION = 'public-node-access-4.2.0-1'


def public_way_access(tags, vehicle_kind):
    if vehicle_kind not in ('auto', 'truck'):
        raise ValueError('road_public_vehicle_kind_invalid')
    keys = ['access', 'vehicle', 'motor_vehicle', 'motorcar' if vehicle_kind == 'auto' else 'hgv']
    # Do not pretend an unparsed condition is unconditional permission.
    if any(any(name.startswith(key + ':') for key in keys) for name in tags):
        return {'include': False, 'reason': 'public_access_condition_unresolved'}
    applicable = [(key, tags[key]) for key in keys if key in tags]
    if not applicable:
        return {'include': True, 'reason': 'native_highway_defaults'}
    key, value = applicable[-1]
    if value in ('yes', 'permissive', 'discouraged') or (value == 'designated' and key != 'access'):
        return {'include': True, 'reason': 'public_access_allowed', 'tag': key, 'value': value}
    if value in ('no', 'private', 'destination', 'customers', 'delivery', 'agricultural', 'forestry', 'permit'):
        return {'include': False, 'reason': 'public_access_not_authorized', 'tag': key, 'value': value}
    return {'include': False, 'reason': 'public_access_value_unresolved', 'tag': key}


def public_node_access(tags, vehicle_kind):
    access = public_way_access(tags, vehicle_kind)
    if not access['include']:
        return access
    if any(name.startswith(('locked:', 'barrier:')) for name in tags) or 'opening_hours' in tags:
        return {'include': False, 'reason': 'node_condition_unresolved'}
    if tags.get('locked', 'no') != 'no':
        return {'include': False, 'reason': 'node_locked_or_unknown'}
    barrier = tags.get('barrier')
    if barrier in (None, 'no'):
        return access
    if barrier not in {'gate', 'lift_gate', 'swing_gate', 'chain', 'entrance', 'toll_booth', 'border_control'}:
        return {'include': False, 'reason': 'node_barrier_requires_verification'}
    if access['reason'] == 'native_highway_defaults':
        return {'include': False, 'reason': 'node_gate_permission_unknown'}
    return access
