"""Compile reviewed internal lines, joining only explicitly evidenced OSM nodes."""
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.road_condition_tags import compile_condition_tags, match_geometry_component


class RoadEndpointConnection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    component: int = Field(ge=0, le=9999)
    endpoint: Literal['start', 'end']
    osm_node_id: int = Field(gt=0, le=9007199254740991)


class NewRoadGeometryEvidence(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: Literal['new_road']
    public_source_sha256: str = Field(pattern='^[a-f0-9]{64}$')
    connections: list[RoadEndpointConnection] = Field(min_length=1, max_length=20000)


def append_reviewed_roads(source: Path, destination: Path, roads: list[dict]):
    """Private build step after permission/vehicle filtering, never an API input.

    Exact evidenced endpoints share nodes. Other coincident vertices, bridges
    and disjoint components remain distinct; no nearest-road connectors exist.
    """
    import osmium

    coordinates, used_nodes = {}, set()
    max_node, max_way = 0, 0

    class Index(osmium.SimpleHandler):
        def node(self, node):
            nonlocal max_node
            max_node = max(max_node, node.id)
            coordinates[node.id] = [node.location.lon, node.location.lat]

        def way(self, way):
            nonlocal max_way
            max_way = max(max_way, way.id)
            used_nodes.update(node.ref for node in way.nodes)

    Index().apply_file(str(source))
    generated_nodes, generated_ways, references = [], [], []
    for road in roads:
        evidence = NewRoadGeometryEvidence.model_validate(road['geometry_evidence'])
        geometry = road['geometry']
        lines = [geometry['coordinates']] if geometry['type'] == 'LineString' else geometry['coordinates']
        links = {(item.component, item.endpoint): item.osm_node_id for item in evidence.connections}
        if (len(links) != len(evidence.connections)
                or {index for index, _ in links} != set(range(len(lines)))):
            raise ValueError('road_new_geometry_component_connection_required')
        for index, line in enumerate(lines):
            # Shared validation of all coordinates and unambiguous orientation.
            match_geometry_component(geometry, line)
            ids = []
            for offset, point in enumerate(line):
                endpoint = 'start' if offset == 0 else 'end' if offset == len(line) - 1 else None
                linked = links.get((index, endpoint))
                if linked is not None:
                    if linked not in used_nodes or any(
                            abs(a - b) > 1e-7 for a, b in zip(point, coordinates[linked])):
                        raise ValueError('road_new_geometry_connection_mismatch')
                    ids.append(linked)
                else:
                    max_node += 1
                    if max_node >= 2 ** 53:
                        raise ValueError('road_new_geometry_identifier_exhausted')
                    generated_nodes.append((max_node, point))
                    ids.append(max_node)
            max_way += 1
            if max_way >= 2 ** 53:
                raise ValueError('road_new_geometry_identifier_exhausted')
            tags = compile_condition_tags({'highway': 'service'}, line,
                {'geometry': geometry, 'conditions': road['conditions']})
            generated_ways.append((max_way, ids, tags))
            references.append({'source_id': road['source_id'], 'import_id': road['import_id'],
                'feature_id': road['feature_id'], 'component': index,
                'way_id': max_way, 'node_ids': ids, 'review_id': road['review_id']})

    # Ordered PBF: original nodes, new nodes, original ways, new ways, relations.
    with osmium.SimpleWriter(str(destination)) as writer:
        class Copy(osmium.SimpleHandler):
            def __init__(self, kind):
                super().__init__()
                self.kind = kind

            def node(self, node):
                if self.kind == 'n':
                    writer.add_node(node)

            def way(self, way):
                if self.kind == 'w':
                    writer.add_way(way)

            def relation(self, relation):
                if self.kind == 'r':
                    writer.add_relation(relation)

        Copy('n').apply_file(str(source))
        for identifier, point in generated_nodes:
            writer.add_node(osmium.osm.mutable.Node(id=identifier, location=point, version=1))
        Copy('w').apply_file(str(source))
        for identifier, ids, tags in generated_ways:
            writer.add_way(osmium.osm.mutable.Way(id=identifier, nodes=ids, tags=tags, version=1))
        Copy('r').apply_file(str(source))
    with destination.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'output_sha256': digest, 'new_internal_components': references,
            'added_nodes': len(generated_nodes), 'added_ways': len(generated_ways)}
