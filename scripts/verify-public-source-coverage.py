#!/usr/bin/env python3
"""Compare downloaded provider polygons with a target; never publish maps.

Provider extents describe acquisition coverage, not actual road completeness.
Requires the isolated public map build environment (Shapely).
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

from shapely.geometry import Polygon, shape
from shapely.ops import unary_union


def parse_poly(text: str):
    """Parse Osmosis polygon rings, retaining exclusions without auto-repair."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        raise ValueError("Incomplete polygon file")
    combined = None
    index = 1
    finished = False
    while index < len(lines):
        label = lines[index]
        index += 1
        if label == "END":
            finished = True
            break
        coords = []
        while index < len(lines) and lines[index] != "END":
            values = lines[index].split()
            if len(values) != 2:
                raise ValueError("Invalid coordinate pair")
            x, y = map(float, values)
            if not (math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90):
                raise ValueError("Invalid geographic coordinates")
            coords.append((x, y))
            index += 1
        if index == len(lines) or len(coords) < 4 or coords[0] != coords[-1]:
            raise ValueError("Unclosed polygon ring")
        index += 1
        polygon = Polygon(coords)
        if polygon.is_empty or not polygon.is_valid:
            raise ValueError("Invalid polygon geometry")
        if label.startswith("!"):
            if combined is None:
                raise ValueError("Hole without outer ring")
            combined = combined.difference(polygon)
        else:
            combined = polygon if combined is None else combined.union(polygon)
    if not finished or index != len(lines) or combined is None:
        raise ValueError("Missing final END or trailing data")
    if combined.is_empty or not combined.is_valid:
        raise ValueError("Invalid polygon geometry")
    return combined


def coverage(target, sources):
    for geometry in [target, *sources]:
        if geometry.geom_type not in {"Polygon", "MultiPolygon"} or geometry.is_empty or not geometry.is_valid:
            raise ValueError("Valid nonempty polygon geometry required")
    if not sources:
        raise ValueError("At least one source required")
    uncovered = target.difference(unary_union(sources))
    return {
        "coverage_verified": uncovered.is_empty,
        "uncovered_bounds": None if uncovered.is_empty else list(uncovered.bounds),
        "road_reference_completeness_verified": False,
        "routing_validated": False,
        "publish_ready": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", type=Path, required=True)
    parser.add_argument("--source-poly", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    region_bytes = args.region.read_bytes()
    region = json.loads(region_bytes)
    target = unary_union([shape(f["geometry"]) for f in region["features"]])
    records, geometries = [], []
    for path in args.source_poly:
        content = path.read_bytes()
        geometry = parse_poly(content.decode("utf-8"))
        geometries.append(geometry)
        records.append({"name": path.name, "sha256": hashlib.sha256(content).hexdigest(),
                        "intersects_target": geometry.intersects(target)})
    report = {"schema_version": 1, "algorithm": "provider-polygon-ordered-v2",
              "region_sha256": hashlib.sha256(region_bytes).hexdigest(),
              "sources": records, **coverage(target, geometries),
              "boundary": "Provider extent only; does not prove dated PBF contents or road connectivity"}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["coverage_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
