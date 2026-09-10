#!/usr/bin/env python3
"""Read-only public OSM source audit; never publishes maps or claims routability.

Run in an isolated build environment with osmium==4.3.1. Up to four passes retain
object IDs, not coordinates or geometry. Memory is proportional to object count.
Only use public-source extracts here, never an internal merged production file.
"""

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any


ROAD_TAGS = ("oneway", "junction", "bridge", "tunnel", "layer", "access",
             "motor_vehicle", "maxheight", "maxweight", "maxspeed", "surface")
Record = dict[str, Any]
RESTRICTION_VALUES = {
    "no_right_turn", "no_left_turn", "no_u_turn", "no_straight_on",
    "only_right_turn", "only_left_turn", "only_u_turn", "only_straight_on",
    "no_entry", "no_exit",
}


def is_restriction(tags: dict) -> bool:
    return (tags.get("type", "").startswith("restriction") or
            any(key == "restriction" or key.startswith("restriction:") for key in tags))


def restriction_structure(obj: Record) -> tuple[list[str], list[str]]:
    """Validate member shape only; connectivity and engine support are separate."""
    tags = obj["tags"]
    value = tags.get("restriction")
    issues, unverified = [], []
    members = {role: [ref for ref in obj["refs"] if ref[2] == role]
               for role in ("from", "via", "to")}
    for role, refs in members.items():
        if not refs:
            issues.append(f"missing_{role}")
    for role, multi_value in (("from", "no_entry"), ("to", "no_exit")):
        refs = members[role]
        if any(ref[0] != "w" for ref in refs):
            issues.append(f"invalid_{role}_type")
        if len(refs) > 1 and value != multi_value:
            # Qualified/conditional values are not interpreted by this audit.
            if value in RESTRICTION_VALUES:
                issues.append(f"invalid_{role}_count")
            else:
                unverified.append(f"unverified_{role}_count")
    via = members["via"]
    if via and not (len(via) == 1 and via[0][0] == "n" or
                    all(ref[0] == "w" for ref in via)):
        issues.append("invalid_via_shape")
    if any(len(refs) != len(set(refs)) for refs in members.values()):
        issues.append("duplicate_role_member")
    if any(ref[2] not in members for ref in obj["refs"]):
        unverified.append("unrecognized_member_role")
    if value not in RESTRICTION_VALUES:
        unverified.append("restriction_value_unverified")
    if tags.get("type") != "restriction" or any(
            key.startswith("restriction:") for key in tags):
        unverified.append("qualified_restriction_unverified")
    return issues, unverified


def read_records(path: Path) -> Iterator[Record]:
    """Copy values immediately: pyosmium objects are transient buffer views."""
    import osmium

    for obj in osmium.FileProcessor(str(path)):
        kind = obj.type_str()
        refs = []
        if kind == "w":
            refs = [("n", node.ref, "") for node in obj.nodes]
        elif kind == "r":
            refs = [(member.type, member.ref, member.role) for member in obj.members]
        yield {"type": kind, "id": obj.id, "tags": dict(obj.tags), "refs": refs}


def restriction_quarantine(reader, anomalies, identifiers):
    """Conservative exclusion inventory, not permission to use the remaining graph.

    Keep original relations untouched. Include all roads sharing known member
    nodes because a missing from/to role cannot be inferred safely.
    """
    nodes, ways = set(), set()
    unlocated = []
    for anomaly in anomalies:
        known = [ref for ref in anomaly['refs'] if ref[1] in identifiers.get(ref[0], set())]
        if not any(ref[0] in ('n', 'w') for ref in known):
            unlocated.append(anomaly['relation_id'])
        nodes.update(ref[1] for ref in known if ref[0] == 'n')
        ways.update(ref[1] for ref in known if ref[0] == 'w')
    # Missing via roles and via-ways need conservative endpoints as well.
    if ways:
        for obj in reader():
            if obj['type'] == 'w' and obj['id'] in ways:
                nodes.update(ref[1] for ref in obj['refs'] if ref[0] == 'n' and ref[1] in identifiers['n'])
    incident = set(ways)
    if nodes:
        for obj in reader():
            if obj['type'] == 'w' and obj['tags'].get('highway') and any(ref[1] in nodes for ref in obj['refs']):
                incident.add(obj['id'])
    return {'policy_version': 'unverified-restrictions-1', 'applied_to_graph': False,
            'relations': anomalies, 'unlocated_relation_ids': sorted(unlocated),
            'exclude_node_ids': sorted(nodes), 'exclude_way_ids': sorted(incident),
            'routing_release_blocked': bool(anomalies),
            'scope_note': 'Conservative source-object inventory; engine enforcement and remaining network validation are required.'}


def audit_records(reader: Callable[[], Iterable[Record]], cities: tuple[str, ...]) -> dict:
    """Check direct references; boundary polygon and routing checks stay separate."""
    identifiers = {kind: set() for kind in ("n", "w", "r")}
    for obj in reader():
        identifiers[obj["type"]].add(obj["id"])

    missing_nodes = 0
    missing_restrictions = 0
    incomplete_ways = set()
    samples = []
    road_count = 0
    restriction_count = 0
    invalid_structures = 0
    unverified_structures = 0
    structure_samples = []
    anomalies = []
    tag_counts = Counter()
    boundaries = {city: [] for city in cities}

    def missing(ref: tuple) -> bool:
        return ref[1] not in identifiers.get(ref[0], set())

    def sample(obj: Record, ref: tuple) -> None:
        if len(samples) < 20:
            samples.append({"object": f'{obj["type"]}{obj["id"]}',
                            "missing": f"{ref[0]}{ref[1]}", "role": ref[2]})

    for obj in reader():
        tags = obj["tags"]
        if obj["type"] == "w":
            if tags.get("highway"):
                road_count += 1
                tag_counts.update(key for key in ROAD_TAGS if key in tags)
            for ref in obj["refs"]:
                if missing(ref):
                    missing_nodes += 1
                    incomplete_ways.add(obj["id"])
                    sample(obj, ref)
        elif obj["type"] == "r":
            if is_restriction(tags):
                restriction_count += 1
                issues, unverified = restriction_structure(obj)
                absent = [ref for ref in obj['refs'] if missing(ref)]
                if issues or unverified or absent:
                    anomalies.append({'relation_id': obj['id'], 'issues': issues,
                                      'unverified': unverified, 'missing_refs': absent,
                                      'refs': obj['refs']})
                invalid_structures += bool(issues)
                unverified_structures += bool(unverified)
                if (issues or unverified) and len(structure_samples) < 20:
                    structure_samples.append({"object": f'r{obj["id"]}',
                                              "issues": issues, "unverified": unverified})
                for ref in obj["refs"]:
                    if missing(ref):
                        missing_restrictions += 1
                        sample(obj, ref)
            name = tags.get("name:zh", tags.get("name"))
            if tags.get("boundary") == "administrative" and name in boundaries:
                boundaries[name].append(obj)

    city_results = []
    for city, matches in boundaries.items():
        status = "missing"
        if len(matches) > 1:
            status = "ambiguous"
        elif matches:
            refs = matches[0]["refs"]
            if not refs or any(missing(ref) or
                               (ref[0] == "w" and ref[1] in incomplete_ways)
                               for ref in refs):
                status = "incomplete_references"
            elif any(ref[0] == "r" for ref in refs):
                status = "nested_members_unverified"
            else:
                status = "references_present_geometry_unverified"
        city_results.append({"name": city, "status": status,
                             "relation_ids": [obj["id"] for obj in matches],
                             "admin_levels": [obj["tags"].get("admin_level")
                                              for obj in matches]})

    return {
        "schema_version": 2,
        "objects": {kind: len(values) for kind, values in identifiers.items()},
        "roads": {"ways": road_count, "tag_counts": dict(tag_counts)},
        "restrictions": restriction_count,
        "references": {"missing_way_nodes": missing_nodes,
                       "missing_restriction_members": missing_restrictions,
                       "incomplete_ways": len(incomplete_ways), "samples": samples},
        "reference_gate": "failed" if missing_nodes or missing_restrictions else "passed",
        "restriction_structure_gate": ("failed" if invalid_structures else
                                       "unverified" if unverified_structures else "passed"),
        "restriction_structure": {"invalid": invalid_structures,
                                  "unverified": unverified_structures,
                                  "samples": structure_samples},
        "restriction_quarantine": restriction_quarantine(reader, anomalies, identifiers),
        "city_boundaries": city_results,
        "routing_validated": False,
        "release_ready": False,
        "limitations": ["Reference checks do not validate restriction semantics or connectivity.",
                        "Member structure checks do not prove turn restrictions are applied by the engine.",
                        "Boundary geometry, full coverage and cross-province detours remain unverified.",
                        "Road tag counts cover all highway types, not validated motorvehicle access.",
                        "No map snapshot is changed by this audit."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True,
                        help="New report path; existing files are never overwritten")
    args = parser.parse_args()
    with args.source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    result = audit_records(lambda: read_records(args.source), ("大庆市", "齐齐哈尔市"))
    # Detect source replacement or modification during the multi-pass audit.
    with args.source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise RuntimeError("Source changed during audit; report not written")
    result["source"] = {"filename": args.source.name, "sha256": digest,
                        "bytes": args.source.stat().st_size, "parser": "pyosmium"}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if (result["reference_gate"] != "passed" or
                 result["restriction_structure_gate"] != "passed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
