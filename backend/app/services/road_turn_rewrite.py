"""Compile closed mandatory exits into explicit prohibited turns.

Only ordinary from-way / via-node / to-way endpoint relations are handled.
Source geometry, exceptions and conditional semantics are never guessed.
"""


def closed_only_target(tags, members, way_nodes, excluded):
    restrictions = {key: value for key, value in tags.items()
                    if key == 'restriction' or key.startswith('restriction:')}
    if (tags.get('type') != 'restriction' or any(key == 'except' or key.startswith('except:') for key in tags)
            or len(restrictions) != 1 or tags.get('restriction') not in {
                'only_right_turn', 'only_left_turn', 'only_straight_on'}):
        return None
    by_role = {role: [(kind, ref) for kind, ref, current in members if current == role]
               for role in ('from', 'via', 'to')}
    if len(members) != 3 or any(len(items) != 1 for items in by_role.values()):
        return None
    approach, via, target = (by_role[role][0] for role in ('from', 'via', 'to'))
    if (approach[0] != 'w' or target[0] != 'w' or via[0] != 'n'
            or approach[1] in excluded or target[1] not in excluded):
        return None
    node = via[1]
    connected = {identifier: sequence for identifier, sequence in way_nodes.items() if node in sequence}
    if approach[1] not in connected or target[1] not in connected:
        raise ValueError('road_turn_rewrite_disconnected_members')
    # A way crossing the junction internally needs directional splitting first.
    # Refuse to encode an ambiguous turn against an unsplit/looped way.
    if any(len(sequence) < 2 or sequence.count(node) != 1 or node not in (sequence[0], sequence[-1])
           for sequence in connected.values()):
        raise ValueError('road_turn_rewrite_requires_split_way')
    return [{'tags': {'type': 'restriction', 'restriction':
                         'no_u_turn' if identifier == approach[1] else 'no_entry'},
             'members': [('w', approach[1], 'from'), ('n', node, 'via'), ('w', identifier, 'to')]}
            for identifier in sorted(connected) if identifier not in excluded]
