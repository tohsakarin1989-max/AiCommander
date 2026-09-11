"""Nominal facility-point coverage from scoped, frozen geographic inputs.

This is neither camera visibility nor vehicle accessibility. Unknown resource
conditions remain unknown instead of becoming evidence of a coverage gap.
"""
import hashlib
import json
import math
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.jurisdiction import JurisdictionAsset
from app.models.governance import SpatialCoverageComparison
from app.models.map_foundation import OperationalArea
from app.services.coverage_area_service import coverage_area
from app.services.offline_map_service import OfflineMapService
from app.utils.geo import haversine_km

VERSION = 'facility-coverage-4.4-2'
RESOURCE_TYPES = ('camera', 'lighting', 'alarm', 'checkpoint')
MAX_RESOURCES = 200
MAX_TARGETS = 2000


def _number(value: Any, minimum: float, maximum: float) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and minimum <= value <= maximum)


def _point(row: dict[str, Any]) -> bool:
    return (row['verified'] is True and row['coordinate_system'] in ('WGS84', 'EPSG:4326')
            and row['geometry_type'] == 'point'
            and _number(row['latitude'], -90, 90) and _number(row['longitude'], -180, 180))


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    # Database timestamps in SQLite lose tzinfo; storage convention is UTC.
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()


def _freeze(asset: JurisdictionAsset) -> dict[str, Any]:
    attributes = asset.attributes if isinstance(asset.attributes, dict) else {}
    snapshot = {key: getattr(asset, key) for key in (
        'id', 'operational_area_id', 'asset_type', 'geometry_type', 'latitude',
        'longitude', 'verified', 'coordinate_system', 'status',
    )} | {
        'valid_from': _iso(asset.valid_from), 'valid_to': _iso(asset.valid_to),
        'updated_at': _iso(asset.updated_at),
        'coverage_radius_m': attributes.get('coverage_radius_m'),
        'operational_status': attributes.get('operational_status'),
        'operational_status_valid_until': attributes.get('operational_status_valid_until'),
        'road_reference_origin': attributes.get('road_reference_origin') is True,
    }
    for key in ('latitude', 'longitude', 'coverage_radius_m'):
        if isinstance(snapshot[key], float) and not math.isfinite(snapshot[key]):
            snapshot[key] = str(snapshot[key])
    return snapshot


def _resource_state(row: dict[str, Any], as_of: datetime) -> str:
    if row['status'] != 'active':
        return 'excluded_inactive'
    for field, before in [('valid_from', True), ('valid_to', False)]:
        if row[field]:
            limit = datetime.fromisoformat(row[field])
            if (before and as_of < limit) or (not before and as_of >= limit):
                return 'unknown_outside_validity'
    try:
        expiry = datetime.fromisoformat(row['operational_status_valid_until'])
        if expiry.utcoffset() is None or as_of >= expiry:
            return 'unknown_status_expired'
    except (TypeError, ValueError):
        return 'unknown_status_validity'
    if row['operational_status'] == 'offline':
        return 'excluded_offline'
    if row['operational_status'] != 'online':
        return 'unknown_operational_status'
    if not _point(row):
        return 'unknown_coordinate'
    if not _number(row['coverage_radius_m'], 0.01, 10000):
        return 'unknown_coverage_radius'
    return 'usable'


def _valid_target(row: dict[str, Any], as_of: datetime) -> bool:
    return _point(row) and all(
        not row[field] or (as_of >= datetime.fromisoformat(row[field]) if before
                          else as_of < datetime.fromisoformat(row[field]))
        for field, before in [('valid_from', True), ('valid_to', False)])


def _coverage_inputs(
    db: Session, area_id: int, *, as_of: datetime,
    disabled_resource_ids: tuple[int, ...] = (),
    movements: dict[int, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Auto-select authorized registered wells and resources; never modify them.

    Movements are explicit hypothetical (latitude, longitude) positions. They
    cannot create a resource, repair unknown source coordinates, or imply access.
    """
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('coverage_read_scope_required')
    allowed = db.info['authorized_area_ids']
    if allowed is not None and area_id not in allowed:
        raise PermissionError('coverage_area_forbidden')
    if as_of.utcoffset() is None:
        raise ValueError('coverage_timezone_required')
    as_of = as_of.astimezone(timezone.utc)
    area = db.query(OperationalArea).populate_existing().filter(OperationalArea.id == area_id,
        OperationalArea.status == 'active').first()
    if area is None:
        raise PermissionError('coverage_area_unavailable')
    boundary = deepcopy(area.boundary)
    map_snapshot = OfflineMapService.current_snapshot(db, area_id)
    base = db.query(JurisdictionAsset).populate_existing().filter(JurisdictionAsset.operational_area_id == area_id)
    resources = [_freeze(row) for row in base.filter(
        JurisdictionAsset.asset_type.in_(RESOURCE_TYPES)).order_by(JurisdictionAsset.id)
        .limit(MAX_RESOURCES + 1).all()]
    targets = [_freeze(row) for row in base.filter(
        JurisdictionAsset.asset_type == 'well', JurisdictionAsset.status == 'active')
        .order_by(JurisdictionAsset.id).limit(MAX_TARGETS + 1).all()]
    if len(resources) > MAX_RESOURCES or len(targets) > MAX_TARGETS:
        raise ValueError('coverage_background_batch_required')
    movements = movements or {}
    resource_ids = {row['id'] for row in resources}
    disabled = set(disabled_resource_ids)
    if (any(type(identifier) is not int for identifier in (*disabled, *movements))
            or not (disabled | movements.keys()) <= resource_ids):
        raise PermissionError('coverage_resource_unavailable')
    for identifier, coordinates in movements.items():
        if (len(coordinates) != 2 or not _number(coordinates[0], -90, 90)
                or not _number(coordinates[1], -180, 180)):
            raise ValueError('coverage_invalid_movement')

    return {'algorithm_version': VERSION, 'area_id': area_id, 'as_of': as_of.isoformat(),
            'area_boundary': boundary,
            'map_snapshot_id': map_snapshot.id if map_snapshot else None,
            'resources': resources, 'targets': targets, 'disabled_resource_ids': sorted(disabled),
            'movements': {str(key): value for key, value in sorted(movements.items())}}


def _input_digest(frozen: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(frozen, sort_keys=True, ensure_ascii=False,
                                    default=str).encode()).hexdigest()


def compare_coverage(
    db: Session, area_id: int, *, as_of: datetime,
    disabled_resource_ids: tuple[int, ...] = (),
    movements: dict[int, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Calculate once from exactly the same frozen inputs used for freshness."""
    frozen = _coverage_inputs(db, area_id, as_of=as_of,
                              disabled_resource_ids=disabled_resource_ids, movements=movements)
    as_of = datetime.fromisoformat(frozen['as_of'])
    resources, targets = frozen['resources'], frozen['targets']
    boundary = frozen['area_boundary']
    disabled = set(frozen['disabled_resource_ids'])
    movements = {int(key): value for key, value in frozen['movements'].items()}

    def calculate(changed: bool) -> dict[str, Any]:
        states, usable = [], []
        for original in resources:
            row = dict(original)
            state = _resource_state(row, as_of)
            if changed and row['id'] in disabled:
                state = 'excluded_by_scenario'
            if changed and row['id'] in movements and state == 'usable':
                row['latitude'], row['longitude'] = movements[row['id']]
            states.append({'resource_id': row['id'], 'state': state})
            if state == 'usable':
                usable.append(row)
        incomplete = not resources or any(row['state'].startswith('unknown') for row in states)
        results = []
        for target in targets:
            covered_by = []
            valid_target = _valid_target(target, as_of)
            if valid_target:
                covered_by = [row['id'] for row in usable if haversine_km(
                    target['latitude'], target['longitude'], row['latitude'], row['longitude']
                ) * 1000 <= row['coverage_radius_m']]
            state = ('nominally_covered' if covered_by else 'unknown'
                     if not valid_target or incomplete else 'outside_known_coverage')
            results.append({'target_id': target['id'], 'state': state, 'covered_by': covered_by})
        return {'targets': results, 'resources': states, 'target_count': len(targets),
                'area_coverage': coverage_area(db, boundary, usable, incomplete=incomplete),
                'covered_count': sum(bool(row['covered_by']) for row in results),
                'overlap_count': sum(len(row['covered_by']) > 1 for row in results),
                'unknown_count': sum(row['state'] == 'unknown' for row in results),
                'outside_known_count': sum(row['state'] == 'outside_known_coverage' for row in results)}

    baseline = calculate(False)
    scenario = calculate(True) if disabled or movements else deepcopy(baseline)
    return {'algorithm_version': VERSION, 'input_digest': _input_digest(frozen), 'input_snapshot': frozen,
            'baseline': baseline, 'scenario': scenario,
            'covered_count_change': scenario['covered_count'] - baseline['covered_count'],
            'evidence_refs': [f"map_asset:{row['id']}" for row in resources + targets],
            'boundary': '仅计算登记井点是否落入设备名义圆形覆盖范围；不是面积、摄像视场、遮挡、道路可达性或防控效果。未登记资源不在评估范围。',
            'road_accessibility': {'state': 'not_calculated'},
            'execution_task_created': False, 'persisted': False}


def _checksum(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def save_comparison(db: Session, result: dict[str, Any], *, created_by: int | None) -> dict[str, Any]:
    """Persist only a server-computed result, not a client-supplied artifact."""
    snapshot = deepcopy(result)
    allowed = db.info.get('authorized_area_ids', ())
    if allowed is not None and snapshot['input_snapshot']['area_id'] not in allowed:
        raise PermissionError('coverage_area_forbidden')
    row = SpatialCoverageComparison(id=str(uuid.uuid4()),
        operational_area_id=snapshot['input_snapshot']['area_id'], created_by=created_by,
        snapshot=snapshot, checksum=_checksum(snapshot))
    db.add(row)
    db.commit()
    return {**snapshot, 'id': row.id, 'persisted': True}


def read_comparison(db: Session, comparison_id: str, *, now: datetime) -> dict[str, Any]:
    """Recheck every referenced resource under current scope before returning history."""
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('coverage_read_scope_required')
    if now.utcoffset() is None:
        raise ValueError('coverage_timezone_required')
    allowed = db.info['authorized_area_ids']
    query = db.query(SpatialCoverageComparison).filter(SpatialCoverageComparison.id == comparison_id)
    if allowed is not None:
        query = query.filter(SpatialCoverageComparison.operational_area_id.in_(allowed))
    row = query.first()
    if row is None:
        raise PermissionError('coverage_history_unavailable')
    if _checksum(row.snapshot) != row.checksum:
        raise ValueError('coverage_snapshot_integrity_failure')
    frozen = row.snapshot['input_snapshot']
    required = {item['id'] for item in frozen['resources'] + frozen['targets']}
    visible = set()
    # SQLite and PostgreSQL have different bind parameter limits.
    identifiers = sorted(required)
    for start in range(0, len(identifiers), 500):
        visible.update(value for (value,) in db.query(JurisdictionAsset.id).filter(
            JurisdictionAsset.operational_area_id == row.operational_area_id,
            JurisdictionAsset.id.in_(identifiers[start:start + 500])).all())
    if visible != required:
        raise PermissionError('coverage_history_unavailable')
    freshness = 'unchanged_inputs'
    try:
        current = _coverage_inputs(db, row.operational_area_id,
            as_of=datetime.fromisoformat(frozen['as_of']),
            disabled_resource_ids=tuple(frozen['disabled_resource_ids']),
            movements={int(key): tuple(value) for key, value in frozen['movements'].items()})
        if _input_digest(current) != row.snapshot['input_digest']:
            freshness = 'source_changed'
        elif any(_resource_state(item, now) != _resource_state(item, datetime.fromisoformat(frozen['as_of']))
                 for item in frozen['resources']) or any(
                     _valid_target(item, now) != _valid_target(item, datetime.fromisoformat(frozen['as_of']))
                     for item in frozen['targets']):
            freshness = 'conditions_expired'
    except ValueError:
        freshness = 'recalculation_required'
    return {**deepcopy(row.snapshot), 'id': row.id, 'persisted': True,
            'historical': True, 'freshness': freshness,
            'history_boundary': '保存的是当时输入和名义覆盖结果，不证明当前设备、道路或现场效果。'}
