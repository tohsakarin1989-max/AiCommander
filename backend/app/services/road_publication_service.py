"""Publish an already governed candidate; paths are worker configuration only.

Files are installed before the short database transition. An interrupted database
commit may leave an unreferenced immutable package, never a half-installed ready
graph. Current permission/source checks still run on every route calculation.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, update

from app.models.road_network import RoadNetworkVersion
from app.models.user import User
from app.services.road_build_job import BUILDER_VERSION, _public_source
from app.services.road_build_plan import recheck_build_plan
from app.services.road_graph_artifact import install_graph_artifact, verify_graph_artifact
from app.services.road_network_contracts import RoadNetworkBinding
from app.services.road_source_revision import source_revision
from app.services.vehicle_router import ENGINE_VERSION
from app.services.public_road_access import NODE_POLICY_VERSION
from app.services.road_refresh_jobs import enqueue_publication


def _authorize(db):
    principal = db.info.get('principal_user_id')
    if type(principal) is not int or 'authorized_area_ids' not in db.info:
        raise PermissionError('road_publish_not_authorized')
    role = db.execute(select(User.role).where(User.id == principal,
        User.is_active.is_(True))).scalar_one_or_none()
    if role != 'admin':
        raise PermissionError('road_publish_not_authorized')


def _check(db, row):
    manifest = row.source_manifest
    if (row.builder_version != BUILDER_VERSION or row.engine_version != ENGINE_VERSION
            or row.status not in ('building', 'ready')
            or manifest.get('build_status') not in ('built_not_published', 'published')):
        raise ValueError('road_publish_candidate_invalid')
    plan = manifest['governance_plan']
    recheck_build_plan(db, plan)
    public = _public_source(db, row.public_bundle_id)
    if public != manifest['public_source_binding']:
        raise ValueError('road_public_bundle_changed')
    revision = source_revision(db, source_ids=plan['inputs']['source_ids'], group_id=row.group_id,
        public_bundle_id=row.public_bundle_id, public_source_sha256=public['source_sha256'])
    if revision != manifest['source_revision']:
        raise ValueError('road_build_source_revision_changed')
    input_hash = hashlib.sha256(json.dumps({'plan': plan['plan_sha256'],
        'public_binding': public['binding_sha256'], 'source_revision': revision['sha256']},
        sort_keys=True).encode()).hexdigest()
    built, filtered = manifest['build_result'], manifest['filter_result']
    if (filtered.get('internal_geometry_and_conditions_overlay_required') is not False
            or filtered.get('public_node_access_policy_version') != NODE_POLICY_VERSION
            or built.get('graph_sha256') != row.graph_sha256
            or built.get('source_sha256') != filtered.get('output_sha256')
            or row.input_sha256 != input_hash
            or row.conditions_sha256 != plan['inputs']['manifest_sha256']
            or plan['inputs']['policy_revision'] != row.policy_revision):
        raise ValueError('road_publish_candidate_invalid')


def publish_road_candidate(db, network_id: str, *, work_root: Path, artifact_root: Path):
    """Own a clean worker session. No API may supply either filesystem root."""
    if db.new or db.dirty or db.deleted:
        raise ValueError('road_publish_requires_clean_session')
    if str(UUID(network_id)) != network_id:
        raise ValueError('road_publish_identifier_invalid')
    try:
        _authorize(db)
        row = db.get(RoadNetworkVersion, network_id, populate_existing=True)
        if row is None:
            raise LookupError('road_network_unavailable')
        _check(db, row)
        frozen = deepcopy(row.source_manifest)
        digest = row.graph_sha256
        ready_binding = RoadNetworkBinding(row.id, row.group_id, row.policy_revision,
            digest, row.artifact_key, row.engine_version, '') if row.status == 'ready' else None
        # Do not hold a database transaction during potentially large I/O.
        db.commit()
        if ready_binding is not None:
            verify_graph_artifact(artifact_root, ready_binding)
            key = ready_binding.artifact_key
        else:
            key = install_graph_artifact(Path(work_root) / network_id / 'compiled' / 'tiles',
                                         artifact_root, expected_sha256=digest)
        _authorize(db)
        row = db.execute(select(RoadNetworkVersion).where(RoadNetworkVersion.id == network_id)
            .with_for_update().execution_options(populate_existing=True)).scalar_one()
        _check(db, row)
        if row.graph_sha256 != digest:
            raise ValueError('road_publish_candidate_changed')
        if row.status == 'ready':
            if row.artifact_key != key:
                raise ValueError('road_publish_candidate_changed')
            db.commit()
            return {'id': network_id, 'status': 'ready', 'created': False, 'artifact_key': key}
        if row.source_manifest != frozen:
            raise ValueError('road_publish_candidate_changed')
        manifest = {**frozen, 'build_status': 'published',
                    'publication': {'published_at': datetime.now(timezone.utc).isoformat(),
                                    'published_by': db.info['principal_user_id'], 'artifact_key': key}}
        changed = db.execute(update(RoadNetworkVersion).where(RoadNetworkVersion.id == network_id,
            RoadNetworkVersion.status == 'building', RoadNetworkVersion.graph_sha256 == digest)
            .values(status='ready', artifact_key=key, source_manifest=manifest))
        if changed.rowcount != 1:
            raise ValueError('road_publish_candidate_changed')
        enqueue_publication(db, network_id, valid_from=row.valid_from)
        db.commit()
        return {'id': network_id, 'status': 'ready', 'created': True, 'artifact_key': key}
    except Exception:
        db.rollback()
        raise
