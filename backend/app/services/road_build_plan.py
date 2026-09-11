"""Join current road governance and reviewed public correspondence for compilation."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from app.models.road_public_alias import RoadPublicAlias
from app.services.road_access_policy import VehicleAssumption
from app.services.road_build_inputs import freeze_internal_road_inputs


def freeze_road_build_plan(db, *, source_ids: list[int], group_id: int, at: datetime,
                           vehicle: VehicleAssumption, public_source_sha256: str):
    if not re.fullmatch('[a-f0-9]{64}', public_source_sha256):
        raise ValueError('road_public_source_hash_invalid')
    inputs = freeze_internal_road_inputs(db, source_ids=source_ids, group_id=group_id, at=at, vehicle=vehicle)
    roads = [*inputs['included'], *inputs['excluded']]
    batches = {road['import_id'] for road in roads}
    rows = db.query(RoadPublicAlias).populate_existing().filter(RoadPublicAlias.import_id.in_(batches),
        RoadPublicAlias.public_source_sha256 == public_source_sha256).order_by(RoadPublicAlias.sequence).all()
    latest = {(row.import_id, row.feature_id, row.osm_way_id): row for row in rows}
    aliases, unresolved, exclusions, new_roads = [], [], set(), []
    excluded = {(road['import_id'], road['feature_id']) for road in inputs['excluded']}
    by_feature = {}
    for (batch, feature, way), row in latest.items():
        if row.decision == 'verified':
            by_feature.setdefault((batch, feature), []).append(row)
    for road in roads:
        key = (road['import_id'], road['feature_id'])
        links = by_feature.get(key, [])
        evidence = road.get('geometry_evidence')
        if evidence and evidence.get('kind') == 'new_road':
            from app.services.road_new_geometry import NewRoadGeometryEvidence
            checked = NewRoadGeometryEvidence.model_validate(evidence)
            if links or checked.public_source_sha256 != public_source_sha256:
                raise ValueError('road_new_geometry_source_conflict')
            if key not in excluded:
                new_roads.append(road)
            continue
        if not links:
            unresolved.append({'source_id': road['source_id'], 'import_id': key[0], 'feature_id': key[1],
                'reason': 'public_correspondence_unresolved',
                'boundary': '可能是新增内部道路或对应尚未核验；不据此认定公共图中不存在。'})
        for row in sorted(links, key=lambda item: item.osm_way_id):
            aliases.append({'alias_id': row.id, 'sequence': row.sequence, 'import_id': row.import_id,
                            'feature_id': row.feature_id, 'osm_way_id': row.osm_way_id,
                            'excluded': key in excluded})
            if key in excluded:
                exclusions.add(row.osm_way_id)
    result = {'schema_version': 'road-build-plan-4.2.0-1', 'inputs': inputs,
              'public_source_sha256': public_source_sha256, 'aliases': aliases,
              'excluded_public_way_ids': sorted(exclusions), 'unresolved': unresolved,
              'new_roads': new_roads,
              'status': 'correspondence_pending' if unresolved else 'ready_for_source_filter',
              'internal_geometry_and_conditions_overlay_required': bool(inputs['included']),
              'graph_ready': False}
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return {**result, 'plan_sha256': hashlib.sha256(encoded.encode()).hexdigest()}


def recheck_build_plan(db, plan):
    inputs = plan['inputs']
    current = freeze_road_build_plan(db, source_ids=inputs['source_ids'], group_id=inputs['group_id'],
        at=datetime.fromisoformat(inputs['condition_time']),
        vehicle=VehicleAssumption.model_validate_json(json.dumps(inputs['vehicle'])),
        public_source_sha256=plan['public_source_sha256'])
    if current != plan:
        raise ValueError('road_build_plan_changed')


def filter_current_road_source(db, *, source_pbf: Path, output: Path, source_ids: list[int],
                               group_id: int, at: datetime, vehicle: VehicleAssumption,
                               public_source_sha256: str):
    from app.services.road_source_filter import filter_road_source
    plan = freeze_road_build_plan(db, source_ids=source_ids, group_id=group_id, at=at,
                                  vehicle=vehicle, public_source_sha256=public_source_sha256)
    if plan['status'] != 'ready_for_source_filter':
        raise ValueError('road_build_correspondence_pending')
    overlays = {}
    excluded = set(plan['excluded_public_way_ids'])
    aliases_by_feature = {}
    for alias in plan['aliases']:
        aliases_by_feature.setdefault((alias['import_id'], alias['feature_id']), []).append(alias)
    for road in plan['inputs']['included']:
        if road in plan['new_roads']:
            continue
        aliases = aliases_by_feature.get((road['import_id'], road['feature_id']), [])
        if not aliases:
            raise ValueError('road_overlay_segment_compilation_required')
        overlay = {'geometry': road['geometry'], 'conditions': road['conditions']}
        for alias in aliases:
            identifier = alias['osm_way_id']
            if identifier in overlays and overlays[identifier] != overlay:
                raise ValueError('road_overlay_source_conflict')
            # Retain excluded components for coverage verification; filtering
            # still removes them and never applies their permission tags.
            overlays[identifier] = overlay
    public_output = output
    if plan['new_roads']:
        output.mkdir(exist_ok=False)
        public_output = output / 'public-filtered'
    result = filter_road_source(source_pbf, public_output,
        excluded_way_ids=excluded, expected_source_sha256=public_source_sha256,
        condition_overlays=overlays, vehicle_kind=vehicle.kind)
    if plan['new_roads']:
        from app.services.road_new_geometry import append_reviewed_roads
        additions = append_reviewed_roads(public_output / 'eligible.osm.pbf',
            output / 'eligible.osm.pbf', plan['new_roads'])
        result['counts'] = {**result['counts'],
            'nodes': result['counts']['nodes'] + additions['added_nodes'],
            'ways': result['counts']['ways'] + additions['added_ways']}
        result.update(additions)
    recheck_build_plan(db, plan)
    result = {**result, 'governance_plan': plan, 'status': 'filtered_not_published',
              'internal_geometry_and_conditions_overlay_required': False,
              'overlay_scope': ('exact_full_way_and_reviewed_new_geometry' if plan['new_roads']
                                else 'exact_full_way_correspondence_only')}
    (Path(output) / 'governance-filter-manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result
