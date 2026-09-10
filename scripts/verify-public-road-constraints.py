#!/usr/bin/env python3
"""Run source-bound public-road regression fixtures against a local Valhalla graph.

This does not certify the complete road network or enable business routing.
Requires pyvalhalla 3.8.3, osmium and shapely in an isolated build environment.
"""

import argparse
import hashlib
import json
from pathlib import Path

import osmium
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union
from valhalla import Actor
from valhalla._valhalla import decode_polyline
from valhalla.config import get_config


SOURCE_SHA = "bfa43dbb42c191d4e8e0a00e390bdcca327d7bc3c4502d879c0f8a719b887b2a"
GRAPH_SHA = "3e0ff861f57a1d1ee0d7248be4a1df6e39657861e77bb0d7df669d2ed2d98ae4"
BOUNDARY_SHA = "ef9f162093c0368e55b3933597b3c6132ce1766c498113057b76332b2badd82d"
WAY_IDS = {250284015, 772434747, 1550481791, 1550481790, 83279635, 678816643}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Source(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.ways = {}
        self.restriction = None

    def way(self, way):
        if way.id in WAY_IDS:
            self.ways[way.id] = {
                "tags": dict(way.tags),
                "nodes": [node.ref for node in way.nodes],
                "coordinates": [(node.lon, node.lat) for node in way.nodes],
            }

    def relation(self, relation):
        if relation.id == 21241409:
            self.restriction = {
                "tags": dict(relation.tags),
                "members": [(m.type, m.ref, m.role) for m in relation.members],
            }


def point(lon, lat):
    return dict(lon=lon, lat=lat, radius=1, search_cutoff=3,
                node_snap_tolerance=0, minimum_reachability=0)


def route(actor, locations, expected_ways):
    correlations = []
    for location, expected in zip(locations, expected_ways, strict=True):
        edges = actor.locate({"locations": [location], "costing": "auto",
                              "verbose": True})[0]["edges"]
        require(bool(edges), "No correlated road")
        require(all(e["edge_info"]["way_id"] == expected for e in edges),
                "Fixture snapped to a different road")
        correlations.append({"way_id": expected,
                             "maximum_distance_m": max(e["distance"] for e in edges)})
    result = actor.route({"locations": locations, "costing": "auto",
                          "units": "kilometers"})["trip"]
    trace = actor.trace_attributes({
        "encoded_polyline": result["legs"][0]["shape"],
        "shape_match": "edge_walk", "costing": "auto",
        "filters": {"action": "include", "attributes": ["edge.way_id"]},
    })
    ways = [edge["way_id"] for edge in trace["edges"]]
    require(ways[0] == expected_ways[0] and ways[-1] == expected_ways[-1],
            "Route endpoints differ from correlated roads")
    return {"distance_km": result["summary"]["length"], "ways": ways,
            "locations": locations, "correlations": correlations,
            "coordinates": decode_polyline(result["legs"][0]["shape"], precision=6, order="lnglat")}


def verify(source_path, config_path, boundary_path):
    require(digest(source_path) == SOURCE_SHA, "Unexpected source version")
    require(digest(boundary_path) == BOUNDARY_SHA, "Unexpected administrative boundary version")
    build = json.loads(config_path.read_text())
    for field in ("tile_extract", "tile_url", "traffic_extract"):
        require(not build["mjolnir"].get(field), f"Unverified alternate graph input: {field}")
    tile_dir = Path(build["mjolnir"]["tile_dir"])
    inventory = hashlib.sha256()
    tiles = sorted(tile_dir.rglob("*.gph"), key=lambda tile: tile.relative_to(tile_dir).as_posix())
    for tile in tiles:
        inventory.update(f"tiles/{tile.relative_to(tile_dir).as_posix()}\t{tile.stat().st_size}\t{digest(tile)}\n".encode())
    require(inventory.hexdigest() == GRAPH_SHA, "Unexpected graph version")
    source = Source()
    source.apply_file(str(source_path), locations=True)
    require(set(source.ways) == WAY_IDS, "Missing source fixture")
    bridge = source.ways[250284015]
    ground = source.ways[772434747]
    require(bridge["tags"].get("oneway") == "yes", "Missing one-way source tag")
    require(bridge["tags"].get("bridge") == "yes" and
            bridge["tags"].get("layer") == "1", "Missing bridge source tags")
    require(not set(bridge["nodes"]) & set(ground["nodes"]), "Crossing shares nodes")
    require(LineString(bridge["coordinates"]).crosses(LineString(ground["coordinates"])),
            "Source geometries do not cross")
    restriction = source.restriction
    require(restriction is not None and
            restriction["tags"].get("restriction") == "no_left_turn", "Missing restriction")
    require(set(restriction["members"]) == {
        ("w", 1550481791, "from"), ("n", 14102424710, "via"),
        ("w", 1550481790, "to")}, "Unexpected restriction members")
    config = get_config(tile_dir=str(tile_dir), tile_extract="")
    config["mjolnir"].update(build["mjolnir"])
    config["mjolnir"].update(tile_dir=str(tile_dir), tile_extract="", tile_url="",
                              traffic_extract="")
    actor = Actor(config)
    ends = bridge["coordinates"]
    require(len(ends) == 2, "One-way fixture geometry changed")
    locations = [point(*(a + (b - a) * t for a, b in zip(*ends))) for t in (.25, .75)]
    forward = route(actor, locations, [250284015, 250284015])
    reverse = route(actor, locations[::-1], [250284015, 250284015])
    require(set(forward["ways"]) == {250284015}, "Forward road changed")
    require(reverse["distance_km"] > forward["distance_km"] * 3 and
            len(set(reverse["ways"])) > 1, "Reverse traversal did not detour")
    turn = route(actor, [point(125.1852727, 46.54446175),
                         point(125.18509545, 46.5444392)], [1550481791, 1550481790])
    require((1550481791, 1550481790) not in list(zip(turn["ways"], turn["ways"][1:]))
            and turn["distance_km"] > .1, "Forbidden left turn traversed")
    crossing = route(actor, [point(125.1071069464629 - .0003, 46.53705224704118 - .00022),
                             point(125.1067703 + (125.1071849 - 125.1067703) * .25,
                                   46.5372619 + (46.5370037 - 46.5372619) * .25)],
                     [250284015, 772434747])
    require((250284015, 772434747) not in list(zip(crossing["ways"], crossing["ways"][1:]))
            and crossing["distance_km"] > .2, "Artificial connection at grade separation")
    boundaries = json.loads(boundary_path.read_text())
    region = unary_union([shape(f["geometry"]) for f in boundaries["features"]])
    boundary_points = [point(123.46410204697392, 47.99915398495962),
                       point(123.46242377891997, 48.00278406255394)]
    require(region.contains(Point(boundary_points[0]["lon"], boundary_points[0]["lat"]))
            and not region.covers(Point(boundary_points[1]["lon"], boundary_points[1]["lat"])),
            "Boundary fixture does not cross from inside to outside")
    require(LineString(source.ways[83279635]["coordinates"]).crosses(region.boundary),
            "Source road does not cross the administrative boundary")
    boundary_route = route(actor, boundary_points, [83279635, 83279635])
    require(set(boundary_route["ways"]) == {83279635} and
            .3 < boundary_route["distance_km"] < .6, "Boundary road continuity failed")
    detour_points = [point(124.86061250530801, 46.07147760051415),
                     point(125.10925235870758, 46.18430857960625)]
    require(all(region.contains(Point(p["lon"], p["lat"])) for p in detour_points),
            "Detour endpoints must both lie inside the two-city region")
    detour_source = LineString(source.ways[678816643]["coordinates"])
    require(detour_source.difference(region).length > .1,
            "Source road does not retain the substantial outside-boundary segment")
    detour = route(actor, detour_points, [678816643, 678816643])
    actual_path = LineString(detour["coordinates"])
    require(all(region.contains(Point(p)) for p in (detour["coordinates"][0], detour["coordinates"][-1])),
            "Returned route endpoints differ from inside-region inputs")
    require(set(detour["ways"]) == {678816643} and 22 < detour["distance_km"] < 24,
            "Unexpected outside-boundary reference route")
    require(actual_path.difference(region).length > .1 and actual_path.crosses(region.boundary),
            "Returned route did not leave and re-enter the administrative region")
    # Degree lengths below only prove a nontrivial intersection, not road distance.
    detour["outside_geometry_degrees"] = actual_path.difference(region).length
    detour["both_endpoints_inside"] = True
    return {"fixture_status": "passed", "network_certified": False,
            "source_sha256": SOURCE_SHA, "graph_sha256": GRAPH_SHA,
            "boundary_sha256": BOUNDARY_SHA,
            "config_sha256": digest(config_path), "tile_count": len(tiles),
            "oneway": {"forward": forward, "reverse": reverse},
            "no_left_turn": turn, "grade_separation": crossing,
            "administrative_boundary_continuity": boundary_route,
            "outside_boundary_detour_between_inside_endpoints": detour,
            "remaining": ["six_malformed_source_restrictions", "business_routing_acceptance"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--boundaries", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.source, args.config, args.boundaries), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
