#!/usr/bin/env python3
"""Build a public-only offline gazetteer from a bound OSM source and region.

Run with the isolated map-build requirements. Never use internal merged data.
No service registration or current-map publication is performed by this tool.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.public_place_index import MAX_PLACES, build_index, search_index  # noqa: E402


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(source: Path, region_directory: Path, output: Path) -> dict:
    """Retain named nodes, ways and areas with typed OSM IDs and label points."""
    import osmium
    from shapely.geometry import Point, shape
    from shapely.ops import unary_union

    if output.exists():
        raise FileExistsError(output)
    manifest = json.loads((region_directory / "region-manifest.json").read_text())
    if manifest.get("algorithm_version") != "city-region-v2-strict-members":
        raise ValueError("Unverified region preparation algorithm")
    source_hash = digest(source)
    if source_hash != manifest["source"]["sha256"]:
        raise ValueError("Public source checksum mismatch")
    geometry_path = region_directory / "extraction-region.geojson"
    declaration = next(item for item in manifest["files"]
                       if item["filename"] == geometry_path.name)
    geometry_hash = digest(geometry_path)
    if geometry_hash != declaration["sha256"]:
        raise ValueError("Public region checksum mismatch")
    collection = json.loads(geometry_path.read_text())
    region = unary_union([shape(feature["geometry"]) for feature in collection["features"]])
    if region.is_empty or not region.is_valid:
        raise ValueError("Invalid extraction geometry")
    factory = osmium.geom.GeoJSONFactory()
    records = {}
    skipped = Counter()
    skip_examples = []
    west, south, east, north = region.bounds

    def reject(identifier: str, reason: str) -> None:
        skipped[reason] += 1
        if len(skip_examples) < 20:
            skip_examples.append({"id": identifier, "reason": reason})

    def save(identifier: str, tags: dict, geometry) -> None:
        name = tags.get("name:zh", tags.get("name", ""))
        if not name:
            return
        if (len(name.strip()) > 120 or not name.strip()
                or any(ord(character) < 32 for character in name)):
            reject(identifier, "invalid_name")
            return
        if geometry.is_empty or not geometry.is_valid:
            reject(identifier, "invalid_geometry")
            return
        if not geometry.intersects(region):
            return
        point = geometry.intersection(region).representative_point()
        aliases = []
        for key in ("name", "name:en", "alt_name", "short_name", "official_name"):
            for alias in tags.get(key, "").split(";"):
                alias = alias.strip()
                if (alias and alias != name and alias not in aliases and len(alias) <= 120
                        and not any(ord(character) < 32 for character in alias)):
                    aliases.append(alias)
        if len(aliases) > 16:
            reject(identifier, "too_many_aliases")
            return
        kind = next((tags[key] for key in ("place", "highway", "amenity", "natural",
                                          "waterway", "building", "boundary") if tags.get(key)), "named_feature")
        if len(kind) > 80:
            reject(identifier, "invalid_kind")
            return
        if identifier not in records and len(records) >= MAX_PLACES:
            raise ValueError("place_count_limit_exceeded")
        records[identifier] = {
            "id": identifier, "name": name, "aliases": aliases, "kind": kind,
            "longitude": point.x, "latitude": point.y,
            "location_role": "name_reference_point",
        }

    class GazetteerReader(osmium.SimpleHandler):
        def node(self, node):
            if "name" not in node.tags and "name:zh" not in node.tags:
                return
            if not node.location.valid():
                reject(f"n{node.id}", "invalid_geometry")
                return
            if west <= node.location.lon <= east and south <= node.location.lat <= north:
                save(f"n{node.id}", dict(node.tags), Point(node.location.lon, node.location.lat))

        def way(self, way):
            if "name" not in way.tags and "name:zh" not in way.tags:
                return
            try:
                geometry = shape(json.loads(factory.create_linestring(way)))
            except RuntimeError:
                reject(f"w{way.id}", "unassemblable_geometry")
                return
            save(f"w{way.id}", dict(way.tags), geometry)

        def area(self, area):
            if "name" not in area.tags and "name:zh" not in area.tags:
                return
            identifier = f'{"w" if area.from_way() else "r"}{area.orig_id()}'
            try:
                geometry = shape(json.loads(factory.create_multipolygon(area)))
            except RuntimeError:
                reject(identifier, "unassemblable_geometry")
                return
            # Only replaces the same OSM way's provisional boundary-line label;
            # never merges separate OSM objects based on matching names.
            save(identifier, dict(area.tags), geometry)

    GazetteerReader().apply_file(str(source), locations=True, idx="flex_mem")
    if digest(source) != source_hash or digest(geometry_path) != geometry_hash:
        raise ValueError("Source changed during gazetteer build")
    if not records:
        raise ValueError("No named public features found")
    source_metadata = {
        "source_sha256": source_hash, "region_sha256": geometry_hash,
        "algorithm": "public-osm-labels-v1", "parser": version("osmium"),
        "skipped": dict(skipped), "skip_examples": skip_examples,
        "coverage": "named_public_nodes_ways_areas_within_extraction_region",
        "location_boundary": "Label reference only; not an entrance, address or routing destination",
    }
    result = build_index(output, (records[key] for key in sorted(records)), source_metadata)
    result["sha256"] = digest(output)
    result["bytes"] = output.stat().st_size
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--region-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.region_directory, args.output),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
