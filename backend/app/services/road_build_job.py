"""Dedicated-session road build job; never call inside a case-save transaction.

The job owns commits so native compilation holds no database write transaction.
It registers a verified build candidate, not an automatically published graph.
Publication must still perform an atomic source/policy check and artifact install.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.map_foundation import PublicMapBundle
from app.models.road_network import RoadNetworkVersion
from app.services.road_access_policy import VehicleAssumption
from app.services.road_build_plan import freeze_road_build_plan, filter_current_road_source, recheck_build_plan
from app.services.road_build_inputs import freeze_internal_road_inputs
from app.services.road_graph_builder import compile_local_graph
from app.services.vehicle_router import ENGINE_VERSION
from app.services.road_source_revision import source_revision


BUILDER_VERSION = 'governed-road-builder-4.2.0-7'


def _public_source(db, bundle_id):
    row = db.execute(select(PublicMapBundle.package_hash, PublicMapBundle.manifest,
        PublicMapBundle.status, PublicMapBundle.license_record).where(PublicMapBundle.id == bundle_id)).mappings().first()
    if row is None or row['status'] != 'accepted':
        raise ValueError('road_public_bundle_unavailable')
    manifest = row['manifest']
    assets = manifest.get('assets', []) if isinstance(manifest, dict) else []
    roads = [asset for asset in assets if isinstance(asset, dict) and asset.get('role') == 'road_source']
    if len(roads) != 1 or not re.fullmatch('[a-f0-9]{64}', str(roads[0].get('sha256', ''))):
        raise ValueError('road_public_bundle_source_binding_missing')
    frozen = {'bundle_id': bundle_id, 'package_hash': row['package_hash'],
              'source_sha256': roads[0]['sha256'], 'license_record': row['license_record']}
    frozen['binding_sha256'] = hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()
    return frozen


def _summary(row, *, created):
    manifest = row.source_manifest
    return {'id': row.id, 'status': row.status, 'build_status': manifest.get('build_status'),
            'graph_sha256': row.graph_sha256, 'created': created,
            'routing_available': row.status == 'ready', 'build_directory_key': row.id}


def run_road_build_job(db, *, source_pbf: Path, work_root: Path, source_ids: list[int],
                       group_id: int, at: datetime, vehicle: VehicleAssumption, public_bundle_id: int):
    """Own a clean, dedicated worker session; all paths are server configuration."""
    if db.new or db.dirty or db.deleted:
        raise ValueError('road_build_requires_clean_session')
    # Authorization must precede even reading public catalog metadata.
    plan_arguments = dict(source_ids=source_ids, group_id=group_id, at=at, vehicle=vehicle)
    freeze_internal_road_inputs(db, **plan_arguments)
    public = _public_source(db, public_bundle_id)
    plan = freeze_road_build_plan(db, **plan_arguments, public_source_sha256=public['source_sha256'])
    if plan['status'] != 'ready_for_source_filter':
        raise ValueError('road_build_correspondence_pending')
    inputs = plan['inputs']
    revision = source_revision(db, source_ids=source_ids, group_id=group_id,
                               public_bundle_id=public_bundle_id, public_source_sha256=public['source_sha256'])
    input_hash = hashlib.sha256(json.dumps({'plan': plan['plan_sha256'],
        'public_binding': public['binding_sha256'], 'source_revision': revision['sha256']}, sort_keys=True).encode()).hexdigest()
    identity = dict(group_id=group_id, policy_revision=inputs['policy_revision'],
                    input_sha256=input_hash, conditions_sha256=inputs['manifest_sha256'],
                    engine_version=ENGINE_VERSION, builder_version=BUILDER_VERSION)
    existing = db.query(RoadNetworkVersion).filter_by(**identity).first()
    if existing is not None:
        return _summary(existing, created=False)
    identifier = str(uuid4())
    row = RoadNetworkVersion(id=identifier, public_bundle_id=public_bundle_id, **identity,
        status='building', valid_from=at,
        valid_until=datetime.fromisoformat(inputs['next_condition_change_at']) if inputs['next_condition_change_at'] else None,
        source_manifest={'internal_area_ids': inputs['internal_area_ids'], 'vehicle': inputs['vehicle'],
                         'governance_plan': plan, 'public_source_binding': public,
                         'source_revision': revision, 'build_status': 'building'})
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(RoadNetworkVersion).filter_by(**identity).first()
        if existing is None:
            raise
        return _summary(existing, created=False)
    directory = Path(work_root) / identifier
    try:
        directory.mkdir(parents=True, exist_ok=False)
        filtered = filter_current_road_source(db, source_pbf=source_pbf, output=directory / 'filtered',
            **plan_arguments, public_source_sha256=public['source_sha256'])
        if filtered['governance_plan'] != plan or filtered['internal_geometry_and_conditions_overlay_required']:
            raise ValueError('road_build_plan_changed')
        # Finish the read transaction too: a long native job must not retain a
        # stale database snapshot or database transaction locks.
        db.commit()
        built = compile_local_graph(directory / 'filtered' / 'eligible.osm.pbf', directory / 'compiled',
                                    expected_source_sha256=filtered['output_sha256'])
        recheck_build_plan(db, plan)
        if _public_source(db, public_bundle_id) != public:
            raise ValueError('road_public_bundle_changed')
        if source_revision(db, source_ids=source_ids, group_id=group_id, public_bundle_id=public_bundle_id,
                           public_source_sha256=public['source_sha256']) != revision:
            raise ValueError('road_build_source_revision_changed')
        row = db.get(RoadNetworkVersion, identifier, populate_existing=True)
        if row.status != 'building':
            raise ValueError('road_build_job_state_changed')
        row.graph_sha256 = built['graph_sha256']
        row.source_manifest = {**row.source_manifest, 'build_status': 'built_not_published',
                               'filter_result': {key: value for key, value in filtered.items() if key != 'governance_plan'},
                               'build_result': built}
        # Keep artifact_key unset and status non-ready. The routing selector
        # cannot accidentally consume a candidate before publication gates.
        db.commit()
        return _summary(row, created=True)
    except Exception as error:
        db.rollback()
        row = db.get(RoadNetworkVersion, identifier, populate_existing=True)
        if row is not None and row.status == 'building':
            row.status = 'failed'
            code = str(error)
            if not re.fullmatch(r'road_[a-z_]+', code):
                code = 'road_graph_build_failed'
            row.source_manifest = {**row.source_manifest, 'build_status': 'failed', 'failure_code': code}
            db.commit()
        raise
