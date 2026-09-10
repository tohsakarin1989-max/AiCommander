#!/usr/bin/env python3
"""Prepare versioned public city boundaries and an explicit extraction margin.

Isolated build tool only. It neither downloads data nor publishes system maps.
Requires osmium, shapely and pyproj in the public map-build environment.
"""

import argparse
import hashlib
import json
import math
from importlib.metadata import version
from pathlib import Path


TARGETS = {
    2755197: {"name": "大庆市", "admin_code": "230600"},
    2755137: {"name": "齐齐哈尔市", "admin_code": "230200"},
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def city_features(source: Path, targets: dict) -> list[dict]:
    """Assemble actual relation rings; do not use envelope as city geometry."""
    import osmium
    from shapely.geometry import shape

    features = {}
    factory = osmium.geom.GeoJSONFactory()
    source_ways = set()
    source_relations = set()
    members = {}
    needed_nodes = set()
    found_nodes = set()

    class SourceIndex(osmium.SimpleHandler):
        def way(self, way):
            source_ways.add(way.id)

        def relation(self, relation):
            source_relations.add(relation.id)
            if relation.id in targets:
                if relation.id in members:
                    raise ValueError(f"Duplicate boundary relation: {relation.id}")
                members[relation.id] = [(m.type, m.ref, m.role) for m in relation.members]

    SourceIndex().apply_file(str(source))
    for identifier in targets:
        if identifier not in members:
            raise ValueError(f"Missing city boundary relation: {identifier}")
        for kind, ref, role in members[identifier]:
            if kind == "r" and role != "subarea":
                raise ValueError(f"Nested geometry is unsupported: {identifier}/{ref}")
            if ((kind == "w" and ref not in source_ways)
                    or (kind == "r" and ref not in source_relations)):
                raise ValueError(f"Missing boundary member: {identifier}/{kind}{ref}")
            if kind == "n":
                if role not in ("label", "admin_centre"):
                    raise ValueError(f"Unsupported boundary node role: {role}")
                needed_nodes.add(ref)
            elif kind == "w" and role not in ("outer", "inner", ""):
                raise ValueError(f"Unsupported boundary way role: {role}")

    class BoundaryReader(osmium.SimpleHandler):
        def node(self, node):
            if node.id in needed_nodes:
                found_nodes.add(node.id)

        def area(self, area):
            if area.from_way() or area.orig_id() not in targets:
                return
            identifier = area.orig_id()
            expected = targets[identifier]
            name = area.tags.get("name:zh", area.tags.get("name"))
            if (name != expected["name"] or area.tags.get("admin_level") != "5"
                    or area.tags.get("ref:admin:CN") != expected["admin_code"]):
                raise ValueError(f"Boundary identity mismatch: relation {identifier}")
            if identifier in features:
                raise ValueError(f"Duplicate boundary relation: {identifier}")
            try:
                geometry = json.loads(factory.create_multipolygon(area))
            except RuntimeError as exc:
                raise ValueError(f"Unassemblable boundary geometry: {identifier}") from exc
            polygon = shape(geometry)
            if polygon.is_empty or not polygon.is_valid:
                raise ValueError(f"Invalid boundary geometry: {identifier}")
            west, south, east, north = polygon.bounds
            if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
                raise ValueError(f"Invalid geographic coordinates: {identifier}")
            features[identifier] = {
                "type": "Feature", "geometry": geometry,
                "properties": {"name": name, "osm_relation_id": identifier,
                               "admin_code": expected["admin_code"],
                               "coordinate_system": "EPSG:4326"},
            }

    BoundaryReader().apply_file(str(source), locations=True, idx="flex_mem")
    if needed_nodes - found_nodes:
        raise ValueError(f"Missing boundary member nodes: {sorted(needed_nodes - found_nodes)}")
    missing = sorted(set(targets) - features.keys())
    if missing:
        raise ValueError(f"Missing or unassemblable city boundaries: {missing}")
    return [features[identifier] for identifier in sorted(features)]


def prepare(source: Path, output: Path, margin_km: float,
            targets: dict | None = None) -> dict:
    """Write a fresh candidate directory; the final manifest is the completion marker."""
    from pyproj import CRS, Transformer
    from shapely.geometry import mapping, shape
    from shapely.ops import transform, unary_union

    if not math.isfinite(margin_km) or not 0 < margin_km <= 500:
        raise ValueError("Margin must be finite and between 0 and 500 km")
    targets = TARGETS if targets is None else targets
    if not targets:
        raise ValueError("At least one target city is required")
    source_digest = digest(source)
    output.mkdir(parents=False, exist_ok=False)
    features = city_features(source, targets)
    union = unary_union([shape(feature["geometry"]) for feature in features])
    center = union.centroid
    projection = CRS.from_proj4(
        f"+proj=aeqd +lat_0={center.y} +lon_0={center.x} +datum=WGS84 +units=m"
    )
    forward = Transformer.from_crs("EPSG:4326", projection, always_xy=True)
    backward = Transformer.from_crs(projection, "EPSG:4326", always_xy=True)
    projected = transform(forward.transform, union)
    extraction = transform(backward.transform, projected.buffer(margin_km * 1000))
    if extraction.is_empty or not extraction.is_valid or not extraction.covers(union):
        raise ValueError("Extraction geometry does not fully cover city boundaries")
    if digest(source) != source_digest:
        raise ValueError("Source changed during boundary preparation")

    collections = {
        "city-boundaries.geojson": {"type": "FeatureCollection", "features": features},
        "extraction-region.geojson": {
            "type": "FeatureCollection", "features": [{
                "type": "Feature", "geometry": mapping(extraction),
                "properties": {"margin_km": margin_km,
                               "purpose": "public_map_extraction_not_travel_range"},
            }],
        },
    }
    files = []
    for filename, collection in collections.items():
        path = output / filename
        with path.open("x", encoding="utf-8") as stream:
            json.dump(collection, stream, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        files.append({"filename": filename, "sha256": digest(path),
                      "bytes": path.stat().st_size})
    result = {
        "schema_version": 1, "status": "region_prepared_not_published",
        "source": {"filename": source.name, "sha256": source_digest,
                   "bytes": source.stat().st_size},
        "tools": {name: version(name) for name in ("osmium", "shapely", "pyproj")},
        "algorithm_version": "city-region-v2-strict-members",
        "cities": [feature["properties"] for feature in features],
        "margin_km": margin_km, "margin_projection": projection.to_string(),
        "extraction_bbox": list(extraction.bounds), "files": files,
        "cross_source_coverage_verified": False, "routing_validated": False,
        "limitations": [
            "The projected margin is an extraction buffer, not a travel-distance claim.",
            "Province extracts may not cover the margin; adjoining sources require verification.",
            "Valid OSM polygons do not prove real-world completeness or administrative authority.",
        ],
    }
    with (output / "region-manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--margin-km", type=float, default=30)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output_directory, args.margin_km),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
