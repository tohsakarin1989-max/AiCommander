#!/usr/bin/env python3
"""Extract whole public road ways plus transitive restriction dependencies.

Not a routing engine or display-map replacement. Use only on public source data
in the isolated build environment. Original source and current maps stay intact.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import osmium
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def scan_ways(source, handler):
    with osmium.io.Reader(str(source), osmium.osm.WAY) as reader:
        osmium.apply(reader, handler)


def extract(source: Path, region_directory: Path, output: Path) -> dict:
    source_hash = digest(source)
    region_path = region_directory / "extraction-region.geojson"
    region_bytes = region_path.read_bytes()
    region_hash = hashlib.sha256(region_bytes).hexdigest()
    manifest = json.loads((region_directory / "region-manifest.json").read_text())
    bindings = [item["sha256"] for item in manifest["files"]
                if item["filename"] == "extraction-region.geojson"]
    if manifest["source"]["sha256"] != source_hash or bindings != [region_hash]:
        raise ValueError("Source or region binding mismatch")
    regions = [shape(item["geometry"]) for item in json.loads(region_bytes)["features"]]
    if not regions or any(g.is_empty or not g.is_valid or g.geom_type not in {"Polygon", "MultiPolygon"} for g in regions):
        raise ValueError("Valid extraction polygons required")
    target = unary_union(regions)
    west, south, east, north = target.bounds
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Invalid geographic extraction bounds")
    output.mkdir(exist_ok=False)
    selected = {"n": set(), "w": set(), "r": set()}
    known_ways = set()
    relations = {}
    restrictions = set()

    class Seeds(osmium.SimpleHandler):
        def way(self, way):
            if not way.tags.get("highway"):
                return
            nodes = list(way.nodes)
            if not nodes or any(not node.location.valid() for node in nodes):
                raise ValueError(f"Missing road geometry: w{way.id}")
            coordinates = [(node.lon, node.lat) for node in nodes]
            geometry = LineString(coordinates) if len(coordinates) > 1 else Point(coordinates[0])
            if geometry.intersects(target):
                selected["w"].add(way.id)
                known_ways.add(way.id)
                selected["n"].update(node.ref for node in nodes)

    Seeds().apply_file(str(source), locations=True, idx="flex_mem")
    seed_count = len(selected["w"])
    if not seed_count:
        raise ValueError("No public roads intersect target")

    class RelationIndex(osmium.SimpleHandler):
        def relation(self, relation):
            if relation.id in relations:
                raise ValueError("Duplicate source relation")
            relations[relation.id] = [(m.type, m.ref, m.role) for m in relation.members]
            if relation.tags.get("type") == "restriction" or any(t.k.startswith("restriction:") or t.k == "restriction" for t in relation.tags):
                restrictions.add(relation.id)

    with osmium.io.Reader(str(source), osmium.osm.RELATION) as reader:
        osmium.apply(reader, RelationIndex())

    # Revisit after added way nodes, so restrictions at newly retained endpoints
    # cannot disappear merely because the first seed was inside the polygon.
    for iteration in range(64):
        previous = tuple(len(selected[k]) for k in ("n", "w", "r"))
        for identifier in restrictions:
            if any(ref in selected.get(kind, ()) for kind, ref, _ in relations[identifier]):
                selected["r"].add(identifier)
        for identifier in list(selected["r"]):
            if identifier not in relations:
                raise ValueError(f"Missing relation: r{identifier}")
            for kind, ref, _ in relations[identifier]:
                if kind not in selected or ref <= 0:
                    raise ValueError("Invalid relation member")
                selected[kind].add(ref)
        needed = selected["w"] - known_ways
        if needed:
            found = set()

            class WayNodes(osmium.SimpleHandler):
                def way(self, way):
                    if way.id in needed:
                        if way.id in found:
                            raise ValueError("Duplicate source way")
                        found.add(way.id)
                        selected["n"].update(node.ref for node in way.nodes)

            scan_ways(source, WayNodes())
            if needed != found:
                raise ValueError(f"Missing member ways: {sorted(needed - found)[:10]}")
            known_ways.update(found)
        if previous == tuple(len(selected[k]) for k in ("n", "w", "r")):
            break
    else:
        raise ValueError("Restriction dependency closure exceeded 64 rounds")

    def verify(path):
        seen = {kind: set() for kind in selected}
        required = {kind: set() for kind in selected}

        class Verify(osmium.SimpleHandler):
            def record(self, obj, kind):
                if obj.id in seen[kind] or not obj.visible:
                    raise ValueError("Duplicate or deleted extracted object")
                seen[kind].add(obj.id)

            def node(self, node):
                self.record(node, "n")
                if not node.location.valid():
                    raise ValueError("Invalid extracted node")

            def way(self, way):
                self.record(way, "w")
                required["n"].update(node.ref for node in way.nodes)

            def relation(self, relation):
                self.record(relation, "r")
                for member in relation.members:
                    if member.type not in required:
                        raise ValueError("Invalid extracted relation member")
                    required[member.type].add(member.ref)

        Verify().apply_file(str(path))
        if seen != selected or any(required[k] - seen[k] for k in seen):
            raise ValueError("Missing extracted references or objects")
        return {kind: len(ids) for kind, ids in seen.items()}

    with TemporaryDirectory(prefix=".roads-", dir=output) as directory:
        candidate = Path(directory) / "candidate.osm.pbf"
        header = osmium.io.Header()
        header.set("generator", "AiCommander-public-road-extract-v1")
        with osmium.SimpleWriter(str(candidate), header=header) as writer:
            class Copy(osmium.SimpleHandler):
                def node(self, node):
                    if node.id in selected["n"]:
                        writer.add_node(node)

                def way(self, way):
                    if way.id in selected["w"]:
                        writer.add_way(way)

                def relation(self, relation):
                    if relation.id in selected["r"]:
                        writer.add_relation(relation)

            Copy().apply_file(str(source))
        counts = verify(candidate)
        if digest(source) != source_hash or digest(region_path) != region_hash:
            raise ValueError("Source changed during extraction")
        result = {
            "schema_version": 1, "algorithm": "whole-roads-restriction-closure-v1",
            "source_sha256": source_hash, "region_sha256": region_hash,
            "seed_road_count": seed_count, "closure_rounds": iteration + 1,
            "objects": counts, "selected_restriction_ids": sorted(selected["r"] & restrictions),
            "excluded_restriction_ids": sorted(restrictions - selected["r"]),
            "artifact": {"filename": "roads.osm.pbf", "sha256": digest(candidate), "bytes": candidate.stat().st_size},
            "reference_complete": True, "source_reference_completeness_verified": False,
            "routing_validated": False, "publish_ready": False,
            "boundary": "Whole intersecting highway ways and transitive restriction dependencies; not all map features or verified motorvehicle access",
        }
        with candidate.open("rb") as stream:
            os.fsync(stream.fileno())
        candidate.chmod(0o400)
        os.link(candidate, output / "roads.osm.pbf")
        with (output / "road-manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--region-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(extract(args.source, args.region_directory, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
