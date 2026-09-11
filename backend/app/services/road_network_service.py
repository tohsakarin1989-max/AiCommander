"""Re-authorize graph selection on every read; never use ORM identity-cache state."""
from datetime import datetime, timezone
import hashlib
import json
import re

from sqlalchemy import or_, select

from app.models.road_network import RoadAccessGroup, RoadAccessMembership, RoadNetworkVersion
from app.models.user import User
from app.models.map_foundation import OperationalArea, UserAreaScope
from app.services.road_network_contracts import RoadNetworkBinding, RoadNetworkUnavailable
from app.services.road_access_policy import VehicleAssumption


def _now():
    return datetime.now(timezone.utc)


def select_network(db, *, analysis_at: datetime, vehicle: VehicleAssumption,
                   engine_version: str) -> RoadNetworkBinding:
    """Select latest applicable authorized graph, not a user-chosen resource list.

    This selects a catalog version, not proof that a location has road coverage.
    Historical queries never fall forward to present conditions. The returned
    binding must still be checked before delivery, even if a newer graph appears.
    """
    user_id = db.info.get('principal_user_id')
    if type(user_id) is not int or user_id <= 0 or 'authorized_area_ids' not in db.info:
        raise RoadNetworkUnavailable()
    if analysis_at.tzinfo is None or analysis_at.utcoffset() is None:
        raise ValueError('analysis_timezone_required')
    current = _now()
    instant = analysis_at.astimezone(timezone.utc)
    statement = (select(RoadNetworkVersion.id)
        .join(RoadAccessGroup, RoadAccessGroup.id == RoadNetworkVersion.group_id)
        .join(RoadAccessMembership, RoadAccessMembership.group_id == RoadAccessGroup.id)
        .join(User, User.id == RoadAccessMembership.user_id)
        .where(User.id == user_id, User.is_active.is_(True),
               RoadAccessMembership.valid_from <= current,
               or_(RoadAccessMembership.valid_until.is_(None), RoadAccessMembership.valid_until > current),
               RoadNetworkVersion.policy_revision == RoadAccessGroup.policy_revision,
               RoadNetworkVersion.status == 'ready', RoadNetworkVersion.engine_version == engine_version,
               RoadNetworkVersion.valid_from <= instant,
               or_(RoadNetworkVersion.valid_until.is_(None), RoadNetworkVersion.valid_until > instant))
        .order_by(RoadNetworkVersion.valid_from.desc(), RoadNetworkVersion.created_at.desc(),
                  RoadNetworkVersion.id.desc()))
    # Stream candidates instead of truncating the first page and incorrectly
    # claiming that no compatible graph exists farther down the catalog.
    for identifier in db.execute(statement.execution_options(yield_per=100)).scalars():
        try:
            binding = resolve_network(db, identifier, analysis_at=analysis_at, vehicle=vehicle)
        except RoadNetworkUnavailable as error:
            if error.code in {'road_network_unavailable', 'road_network_not_ready',
                              'road_conditions_not_available_for_time', 'road_graph_vehicle_mismatch',
                              'road_graph_vehicle_binding_missing'}:
                continue
            # Corrupt metadata is an error, not permission to silently use old data.
            raise
        if binding.engine_version == engine_version:
            return binding
    raise RoadNetworkUnavailable('road_compatible_network_unavailable')


def resolve_network(db, network_id: str, *, analysis_at: datetime,
                    vehicle: VehicleAssumption | None = None) -> RoadNetworkBinding:
    """Without vehicle, select inventory only; calculations must supply it."""
    user_id = db.info.get('principal_user_id')
    if type(user_id) is not int or user_id <= 0 or 'authorized_area_ids' not in db.info:
        raise RoadNetworkUnavailable()
    if analysis_at.tzinfo is None or analysis_at.utcoffset() is None:
        raise ValueError('analysis_timezone_required')
    instant = analysis_at.astimezone(timezone.utc)
    current = _now()
    # Permission validity is current even when analyzing a historical incident.
    row = db.execute(select(
        RoadNetworkVersion.id, RoadNetworkVersion.group_id, RoadNetworkVersion.policy_revision,
        RoadNetworkVersion.public_bundle_id,
        RoadNetworkVersion.graph_sha256, RoadNetworkVersion.artifact_key,
        RoadNetworkVersion.input_sha256, RoadNetworkVersion.conditions_sha256,
        RoadNetworkVersion.engine_version, RoadNetworkVersion.builder_version,
        RoadNetworkVersion.source_manifest,
        User.role,
        RoadNetworkVersion.status, RoadNetworkVersion.valid_from, RoadNetworkVersion.valid_until,
    ).join(RoadAccessGroup, RoadAccessGroup.id == RoadNetworkVersion.group_id)
      .join(RoadAccessMembership, RoadAccessMembership.group_id == RoadAccessGroup.id)
      .join(User, User.id == RoadAccessMembership.user_id)
      .where(RoadNetworkVersion.id == network_id, User.id == user_id, User.is_active.is_(True),
             RoadAccessMembership.valid_from <= current,
             or_(RoadAccessMembership.valid_until.is_(None), RoadAccessMembership.valid_until > current),
             RoadNetworkVersion.policy_revision == RoadAccessGroup.policy_revision)).mappings().first()
    if row is None:
        raise RoadNetworkUnavailable()
    if row['status'] != 'ready':
        raise RoadNetworkUnavailable('road_network_not_ready')
    manifest = row['source_manifest']
    internal_areas = manifest.get('internal_area_ids') if isinstance(manifest, dict) else None
    if not isinstance(internal_areas, list) or any(type(value) is not int or value <= 0 for value in internal_areas):
        raise RoadNetworkUnavailable('road_network_integrity_metadata_invalid')
    scope = db.info['authorized_area_ids']
    if row['role'] != 'admin':
        # Request scope is a ceiling, not a permanent grant during a long job.
        # Read live grants so an area revocation or admin demotion invalidates
        # graph access without waiting for the next HTTP request/session.
        current_scope = set(db.execute(select(UserAreaScope.operational_area_id)
            .join(OperationalArea, OperationalArea.id == UserAreaScope.operational_area_id)
            .where(UserAreaScope.user_id == user_id, OperationalArea.status == 'active',
                   UserAreaScope.access_level.in_(['read', 'write', 'manage']))).scalars())
        scope = current_scope if scope is None else current_scope.intersection(scope)
    if scope is not None and not set(internal_areas).issubset(set(scope)):
        raise RoadNetworkUnavailable()
    vehicle_key = None
    if vehicle is not None:
        try:
            compiled_vehicle = VehicleAssumption.model_validate(manifest.get('vehicle'))
        except ValueError as error:
            raise RoadNetworkUnavailable('road_graph_vehicle_binding_missing') from error
        vehicle_key = vehicle.model_dump(exclude={'source'})
        if compiled_vehicle.model_dump(exclude={'source'}) != vehicle_key:
            raise RoadNetworkUnavailable('road_graph_vehicle_mismatch')
    # SQLite drops timezone metadata; all persisted catalog timestamps are UTC.
    def utc(value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if instant < utc(row['valid_from']) or (row['valid_until'] and instant >= utc(row['valid_until'])):
        raise RoadNetworkUnavailable('road_conditions_not_available_for_time')
    for name in ('graph_sha256', 'artifact_key', 'input_sha256', 'conditions_sha256'):
        if not isinstance(row[name], str) or not re.fullmatch('[a-f0-9]{64}', row[name]):
            raise RoadNetworkUnavailable('road_network_integrity_metadata_invalid')
    if 'governance_plan' in manifest or row['builder_version'].startswith('governed-road-builder-'):
        from app.services.public_road_access import NODE_POLICY_VERSION
        filter_result = manifest.get('filter_result')
        if (not isinstance(filter_result, dict)
                or filter_result.get('public_node_access_policy_version') != NODE_POLICY_VERSION):
            raise RoadNetworkUnavailable('road_node_policy_rebuild_required')
        from app.services.road_source_revision import source_revision
        revision = manifest.get('source_revision')
        try:
            plan = manifest['governance_plan']
            if (not isinstance(revision, dict) or revision.get('group_id') != row['group_id']
                    or revision.get('public_bundle_id') != row['public_bundle_id']
                    or revision.get('source_ids') != plan['inputs']['source_ids']
                    or revision.get('internal_area_ids') != internal_areas
                    or revision.get('public_source_sha256') != plan['public_source_sha256']):
                raise ValueError('missing source revision')
            current_revision = source_revision(db, source_ids=revision['source_ids'], group_id=row['group_id'],
                public_bundle_id=revision['public_bundle_id'], public_source_sha256=revision['public_source_sha256'])
        except (KeyError, TypeError, ValueError, PermissionError) as error:
            raise RoadNetworkUnavailable('road_network_source_revision_unavailable') from error
        if current_revision != revision:
            raise RoadNetworkUnavailable('road_network_sources_changed')
    cache = {'schema': 'road-cache-4.2.0-1', 'principal': user_id,
             'source_revision': manifest.get('source_revision'),
             'vehicle': vehicle_key,
             'data_scope': None if scope is None else sorted(set(scope)),
             'analysis_at': instant.isoformat(),
             **{key: row[key] for key in ('id', 'group_id', 'policy_revision', 'graph_sha256',
                 'input_sha256', 'conditions_sha256', 'engine_version', 'builder_version')}}
    cache_key = hashlib.sha256(json.dumps(cache, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return RoadNetworkBinding(row['id'], row['group_id'], row['policy_revision'], row['graph_sha256'],
                              row['artifact_key'], row['engine_version'], cache_key)


def recheck_network(db, binding: RoadNetworkBinding, *, analysis_at: datetime,
                    vehicle: VehicleAssumption | None = None) -> None:
    """Call after calculation and before cache/file delivery, including cache hits."""
    if resolve_network(db, binding.network_id, analysis_at=analysis_at, vehicle=vehicle) != binding:
        raise RoadNetworkUnavailable('road_network_changed')
