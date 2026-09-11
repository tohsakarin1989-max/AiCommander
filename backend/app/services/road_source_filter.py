"""Remove server-resolved prohibited OSM ways without weakening restrictions.

An upstream authorized compiler resolves internal/public road aliases. This
module accepts that exact frozen way-id set, not arbitrary user API parameters.
"""
import hashlib
import json
from pathlib import Path


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def filter_road_source(source: Path, output: Path, *, excluded_way_ids: set[int], expected_source_sha256: str,
                       condition_overlays: dict | None = None, vehicle_kind: str = 'auto'):
    import osmium
    from app.services.road_condition_tags import compile_condition_tags, match_geometry_component
    from app.services.public_road_access import public_way_access, public_node_access, POLICY_VERSION, NODE_POLICY_VERSION
    from app.services.road_turn_rewrite import closed_only_target
    public_way_access({}, vehicle_kind)  # Validate before reading or creating files.
    condition_overlays = {} if condition_overlays is None else condition_overlays
    if not isinstance(condition_overlays, dict) or any(type(key) is not int or key <= 0 for key in condition_overlays):
        raise ValueError('road_overlay_ids_invalid')
    if not isinstance(excluded_way_ids, set) or any(type(value) is not int or value <= 0 for value in excluded_way_ids):
        raise ValueError('road_exclusion_ids_invalid')
    requested_exclusions = sorted(excluded_way_ids)
    excluded_way_ids = set(excluded_way_ids)
    source = Path(source).resolve(strict=True)
    if _digest(source) != expected_source_sha256:
        raise ValueError('road_source_checksum_mismatch')
    nodes, ways, referenced_nodes, relations = set(), set(), set(), {}
    compiled_tags = {}
    coverage = {}
    component_references = []
    access_exclusions = []
    node_restrictions = {}
    way_nodes = {}

    class Index(osmium.SimpleHandler):
        def node(self, node):
            if node.id in nodes or not node.location.valid():
                raise ValueError('road_source_node_invalid')
            nodes.add(node.id)
            access = public_node_access(dict(node.tags), vehicle_kind)
            if not access['include']:
                node_restrictions[node.id] = access

        def way(self, way):
            if way.id in ways:
                raise ValueError('road_source_duplicate_way')
            ways.add(way.id)
            way_nodes[way.id] = tuple(node.ref for node in way.nodes)
            referenced_nodes.update(node.ref for node in way.nodes)
            if way.id not in condition_overlays:
                access = public_way_access(dict(way.tags), vehicle_kind)
                if not access['include']:
                    excluded_way_ids.add(way.id)
                    access_exclusions.append({'way_id': way.id, **access})
            if way.id in condition_overlays:
                overlay = condition_overlays[way.id]
                coordinates = [[node.lon, node.lat] for node in way.nodes]
                component, reverse, count = match_geometry_component(overlay['geometry'], coordinates)
                key = hashlib.sha256(json.dumps(overlay, sort_keys=True, separators=(',', ':'),
                                                allow_nan=False).encode()).hexdigest()
                matched, expected = coverage.setdefault(key, (set(), count))
                if component in matched or expected != count:
                    raise ValueError('road_overlay_duplicate_component_correspondence')
                matched.add(component)
                component_references.append({'way_id': way.id, 'overlay_sha256': key,
                    'component_index': component, 'reversed': reverse, 'excluded': way.id in excluded_way_ids})
                if way.id not in excluded_way_ids:
                    compiled_tags[way.id] = compile_condition_tags(dict(way.tags), coordinates, overlay)

        def relation(self, relation):
            if relation.id in relations:
                raise ValueError('road_source_duplicate_relation')
            relations[relation.id] = (dict(relation.tags), [(m.type, m.ref, m.role) for m in relation.members])

    Index().apply_file(str(source), locations=bool(condition_overlays))
    if not set(condition_overlays).issubset(ways):
        raise ValueError('road_overlay_way_missing')
    if any(matched != set(range(expected)) for matched, expected in coverage.values()):
        raise ValueError('road_overlay_component_correspondence_missing')
    if not excluded_way_ids.issubset(ways):
        raise ValueError('road_exclusion_way_missing')
    if not referenced_nodes.issubset(nodes):
        raise ValueError('road_source_node_reference_missing')
    known = {'n': nodes, 'w': ways, 'r': set(relations)}
    for _, members in relations.values():
        if any(kind not in known or ref not in known[kind] for kind, ref, _ in members):
            raise ValueError('road_source_relation_reference_missing')
    dropped = set()
    dropped_reasons = {}
    rewritten_members = {}
    generated_turns = []
    next_relation_id = max(relations, default=0) + 1
    while True:
        previous = len(dropped)
        for identifier, (tags, members) in relations.items():
            if identifier in dropped or not any(
                    (kind == 'w' and ref in excluded_way_ids) or (kind == 'r' and ref in dropped)
                    for kind, ref, _ in members):
                continue
            restrictions = [value for key, value in tags.items() if key == 'restriction' or key.startswith('restriction:')]
            if tags.get('type') == 'restriction' or restrictions:
                replacement = closed_only_target(tags, members, way_nodes, excluded_way_ids)
                if replacement is not None:
                    for turn in replacement:
                        if next_relation_id >= 2 ** 63:
                            raise ValueError('road_turn_rewrite_id_exhausted')
                        generated_turns.append({'relation_id': next_relation_id,
                            'source_relation_id': identifier, **turn})
                        next_relation_id += 1
                    dropped_reasons[identifier] = 'only_target_excluded_rewritten'
                    dropped.add(identifier)
                    continue
                from_members = [(kind, ref) for kind, ref, role in members if role == 'from']
                to_members = [(kind, ref) for kind, ref, role in members if role == 'to']
                via_members = [(kind, ref) for kind, ref, role in members if role == 'via']
                if (tags.get('type') == 'restriction'
                        and restrictions == ['no_entry']
                        and 'restriction' in tags and 'except' not in tags
                        and len(from_members) > 1 and len(to_members) == 1
                        and len(via_members) == 1 and via_members[0][0] == 'n'
                        and all(kind == 'w' for kind, _ in from_members + to_members)
                        and all(role in ('from', 'to', 'via') for _, _, role in members)
                        and len(set(members)) == len(members)
                        and to_members[0][1] not in excluded_way_ids
                        and any(ref not in excluded_way_ids for _, ref in from_members)):
                    # Each from member forbids its own approach to the same
                    # target. Remove only excluded approaches, not the surviving
                    # restriction. Conditional/mode-specific cases stay closed.
                    rewritten_members[identifier] = [member for member in members
                        if not (member[0] == 'w' and member[1] in excluded_way_ids)]
                    continue
                if from_members and all(kind == 'w' and ref in excluded_way_ids for kind, ref in from_members):
                    # No surviving approach can trigger this relation, including
                    # only_* restrictions. Removing its target alone is NOT safe.
                    dropped_reasons[identifier] = 'all_from_ways_excluded'
                elif (restrictions and all(value in {'no_left_turn', 'no_right_turn', 'no_straight_on',
                        'no_u_turn', 'no_entry', 'no_exit'} for value in restrictions)
                        and len(from_members) == len(to_members) == 1 and via_members
                        and from_members[0][0] == to_members[0][0] == 'w'
                        and (all(kind == 'w' for kind, _ in via_members)
                             or (len(via_members) == 1 and via_members[0][0] == 'n'))
                        and all(kind in ('n', 'w') and role in ('from', 'to', 'via') for kind, _, role in members)):
                    dropped_reasons[identifier] = 'prohibited_sequence_no_longer_exists'
                else:
                    # An only_* target, partially removed multi-from relation,
                    # or unparsed conditional structure needs a real rewrite.
                    raise ValueError('road_exclusion_requires_turn_rewrite')
            else:
                dropped_reasons[identifier] = 'member_removed'
            dropped.add(identifier)
        if len(dropped) == previous:
            break
    output = Path(output)
    output.mkdir(exist_ok=False)
    destination = output / 'eligible.osm.pbf'
    counts = {'nodes': 0, 'ways': 0, 'relations': 0}
    with osmium.SimpleWriter(str(destination)) as writer:
        class Copy(osmium.SimpleHandler):
            def node(self, node):
                if node.id in node_restrictions:
                    # A compiled barrier splits the edge at the real source
                    # node. Do not delete entire roads or fabricate a connector.
                    # The source retains conditional provenance. The effective
                    # graph must not let a more specific conditional tag undo
                    # a hard exclusion already resolved by server policy.
                    tags = {key: value for key, value in dict(node.tags).items()
                            if not key.startswith(('access:', 'vehicle:', 'motor_vehicle:',
                                                   'motorcar:', 'hgv:'))}
                    tags = {**tags, 'barrier': 'gate', 'access': 'no',
                            'vehicle': 'no', 'motor_vehicle': 'no', 'motorcar': 'no', 'hgv': 'no'}
                    writer.add_node(node.replace(tags=tags))
                else:
                    writer.add_node(node)
                counts['nodes'] += 1

            def way(self, way):
                if way.id not in excluded_way_ids:
                    writer.add_way(way.replace(tags=compiled_tags[way.id]) if way.id in compiled_tags else way)
                    counts['ways'] += 1

            def relation(self, relation):
                if relation.id not in dropped:
                    writer.add_relation(relation.replace(members=rewritten_members[relation.id])
                        if relation.id in rewritten_members else relation)
                    counts['relations'] += 1
        Copy().apply_file(str(source))
        for turn in generated_turns:
            writer.add_relation(osmium.osm.mutable.Relation(id=turn['relation_id'], version=1,
                tags=turn['tags'], members=turn['members']))
            counts['relations'] += 1
    if _digest(source) != expected_source_sha256:
        raise ValueError('road_source_changed_during_filter')
    report = {'schema_version': 'road-source-filter-4.2.0-1', 'source_sha256': expected_source_sha256,
              'output_sha256': _digest(destination), 'excluded_way_ids': sorted(excluded_way_ids),
              'condition_overlay_way_ids': sorted(compiled_tags),
              'requested_excluded_way_ids': requested_exclusions,
              'public_access_policy_version': POLICY_VERSION, 'vehicle_kind': vehicle_kind,
              'public_node_access_policy_version': NODE_POLICY_VERSION,
              'node_access_restrictions': [{'node_id': identifier, **access}
                                           for identifier, access in sorted(node_restrictions.items())],
              'public_access_exclusions': sorted(access_exclusions, key=lambda item: item['way_id']),
              'component_references': sorted(component_references, key=lambda item: item['way_id']),
              'dropped_relation_reasons': dropped_reasons,
              'generated_turn_restrictions': generated_turns,
              'rewritten_relations': [{'relation_id': identifier,
                  'reason': 'excluded_no_entry_approaches_removed',
                  'original_members': relations[identifier][1], 'members': members}
                  for identifier, members in sorted(rewritten_members.items())],
              'dropped_relation_ids': sorted(dropped), 'counts': counts, 'status': 'filtered_not_published'}
    (output / 'filter-manifest.json').write_text(json.dumps(report, indent=2))
    return report
