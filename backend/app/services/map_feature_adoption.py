"""Legacy UI/GIS adapters into the governed source/identity/adoption ledger.

The compatibility endpoints supply EPSG:4326 GeoJSON or explicit latitude /
longitude fields. They never infer a projected CRS and never identify by name.
Manual edits name an existing asset explicitly; that is an auditable observation,
not permission for later uploads to inherit the human decision.
"""
from copy import deepcopy
import math
import json
from types import SimpleNamespace

from app.database import require_area_manage_access
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSource, MapImportTemplate, MapFeatureClaim, MapIngestRun, OperationalArea
from app.services.facility_identity_service import FacilityIdentityService
from app.services.map_foundation_service import MapFoundationService as Foundation, SOURCE_TRUST_RANKS
from app.services.map_import_contract import FIELDS, GROUPS
from app.services.map_ingest_execution import source_for_write, _execute
from app.services.map_ingest_plan import resolve_asset, group_plan, _group_values, _set_values


RESERVED = {'source_id', 'source_key', 'source_trust_rank', 'source_revision', 'source_identity_id',
            'identity_decision_id', 'field_groups', 'vocabulary'}
EXTRAS = ('description', 'status', 'risk_level', 'confidence_score', 'tags', 'verified')


def _json(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=Foundation._json_safe))


def area_for_write(db, area_id=None):
    area_id = area_id or db.info.get('default_operational_area_id')
    if area_id is None and db.info.get('principal_user_id') is None and 'authorized_area_ids' not in db.info:
        area_id = Foundation.ensure_default_area(db).id
    area_id = require_area_manage_access(db, area_id)
    area = db.query(OperationalArea).filter_by(id=area_id, status='active').first()
    if area is None:
        raise ValueError('operational_area_not_found')
    if db.bind.dialect.name == 'postgresql':
        db.query(OperationalArea.id).filter_by(id=area_id).with_for_update().one()
    return area


def _catalog(db, area, label, channel):
    # Labels select a *new compatibility namespace*, never a caller-selected
    # registered source or caller-controlled trust rank.
    token = Foundation._hash_json([area.id, channel, label])[:32]
    key = 'compat-v9:' + token
    source = db.query(MapSource).filter_by(source_key=key).first()
    if source is None:
        kind = 'manual' if channel == 'manual' else 'internal_gis' if channel == 'geojson' else 'ledger'
        source = MapSource(source_key=key, name=f'兼容{channel}入口：{label}'[:200], source_type=kind,
            trust_rank=SOURCE_TRUST_RANKS[kind], operational_area_id=area.id, status='active',
            configuration={'adapter': 'map-feature-adoption-9.1', 'channel': channel,
                           'source_label': label, 'coordinate_contract': 'EPSG:4326'})
        db.add(source)
        db.flush()
    source = source_for_write(db, source.id, db.info.get('principal_user_id'))
    template = db.query(MapImportTemplate).filter_by(source_id=source.id, name='兼容标准要素', version=1).first()
    if template is None:
        template = MapImportTemplate(source_id=source.id, name='兼容标准要素', version=1,
            field_mapping={key: key for key, *_ in FIELDS}, coordinate_system='wgs84',
            coordinate_unit='degree', axis_order='lon_lat', header_row=1, is_active=True)
        db.add(template)
        db.flush()
    return source, template


def _geometry(payload, boundary):
    geometry = deepcopy(payload.get('geometry'))
    kind = str(payload.get('geometry_type') or 'point').lower()
    if geometry is None and payload.get('longitude') is not None and payload.get('latitude') is not None:
        if kind not in {'point'}:
            raise ValueError('complete_geometry_required|线、面不能由中心点代替')
        geometry = {'type': 'Point', 'coordinates': [payload['longitude'], payload['latitude']]}
    if geometry is None:
        return None, None, None
    if not isinstance(geometry, dict):
        raise ValueError('invalid_geometry|几何必须为 GeoJSON 对象')
    try:
        def point(value):
            return isinstance(value, (list, tuple)) and len(value) >= 2 and all(
                isinstance(x, (int, float)) and not isinstance(x, bool) for x in value)
        def line(value):
            return isinstance(value, list) and len(value) >= 2 and all(point(p) for p in value)
        def polygon(value):
            return isinstance(value, list) and bool(value) and all(
                line(ring) and len(ring) >= 4 and ring[0] == ring[-1] for ring in value)
        validators = {'Point': point, 'LineString': line, 'Polygon': polygon,
            'MultiPoint': lambda v: isinstance(v, list) and bool(v) and all(point(p) for p in v),
            'MultiLineString': lambda v: isinstance(v, list) and bool(v) and all(line(p) for p in v),
            'MultiPolygon': lambda v: isinstance(v, list) and bool(v) and all(polygon(p) for p in v)}
        if not validators.get(geometry.get('type'), lambda _: False)(geometry.get('coordinates')):
            raise ValueError('invalid geometry')
        def points(value):
            if isinstance(value, (list, tuple)) and value and isinstance(value[0], (int, float)):
                yield value
            elif isinstance(value, (list, tuple)):
                for child in value:
                    yield from points(child)
        vertices = list(points(geometry['coordinates']))
        if len(vertices) > 100000:
            raise ValueError('geometry_too_large')
        if not vertices or any(len(p) < 2 or not math.isfinite(float(p[0])) or not math.isfinite(float(p[1]))
            or not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90 for p in vertices):
            raise ValueError('invalid coordinates')
        if boundary and any(not Foundation._point_in_area_boundary(p[0], p[1], boundary) for p in vertices):
            raise ValueError('outside_operational_area|几何超出厂区范围，需核对来源')
    except (TypeError, KeyError, ValueError) as exc:
        if str(exc).startswith('outside_'):
            raise
        raise ValueError('invalid_geometry|需要完整、有效的 EPSG:4326 几何') from exc
    # This display anchor is not a road entrance. The complete geometry remains
    # authoritative and is never replaced by this convenience location.
    return geometry, sum(p[0] for p in vertices) / len(vertices), sum(p[1] for p in vertices) / len(vertices)


def _normalize(source, template, payload, boundary):
    attributes = deepcopy(payload.get('attributes') or {})
    if RESERVED & set(attributes):
        raise ValueError('reserved_source_metadata|来源和字段采用元数据不可由普通字段指定')
    geometry, longitude, latitude = _geometry(payload, boundary)
    declared = str(payload.get('coordinate_system') or attributes.get('coordinate_system') or 'epsg:4326').lower()
    if declared not in {'epsg:4326', 'wgs84'}:
        raise ValueError('coordinate_template_required|非 WGS84 资料请使用已确认坐标模板导入')
    raw = {**attributes, **payload, 'longitude': longitude, 'latitude': latitude}
    external = payload.get('external_id')
    if not external and geometry is None:
        raw['external_id'] = '__unidentified_observation__'
    value = Foundation._normalize_row(source, template, _json(raw),
        area_boundary=None, geometry_state='set' if geometry else 'not_provided')
    value['external_id'] = external
    value['canonical_key'] = 'area:' + str(source.operational_area_id) + ':' + Foundation._hash_json(
        {'source_key': source.source_key, 'external_id': external} if external else
        {'source_key': source.source_key, 'name': payload['name'], 'asset_type': payload['asset_type'], 'geometry': geometry})[:24]
    value.update(geometry=geometry, geometry_type=geometry['type'].lower() if geometry else payload.get('geometry_type', 'point'),
        longitude=longitude, latitude=latitude, source=payload.get('source') or source.source_type,
        verified=bool(payload.get('verified')) if external or source.source_type == 'manual' else False,
        verification_state='human_verified' if payload.get('verified') and source.source_type == 'manual' else
            'identity_pending' if not external else 'source_recorded')
    value['attributes'] = {**attributes, **value['attributes'], 'original_coordinate_unit': 'degree'}
    for key in EXTRAS:
        if key in payload and key != 'verified':
            value[key] = deepcopy(payload[key])
    states = {group: 'set' if group == 'geometry' and geometry else 'not_provided' for group in GROUPS}
    for group in ('water_cut', 'production'):
        if any(attributes.get(key) is not None for key in GROUPS[group]):
            states[group] = 'set'
    return value, states


def preview_payload(db, payload, *, channel='legacy'):
    """Compatibility preview validates but creates no sources, runs or assets."""
    area = area_for_write(db, payload.get('operational_area_id'))
    source = SimpleNamespace(source_key='preview', operational_area_id=area.id,
                             source_type='internal_gis' if channel == 'geojson' else 'ledger')
    template = SimpleNamespace(field_mapping={key: key for key, *_ in FIELDS}, axis_order='lon_lat',
                               coordinate_system='wgs84', transformation=None)
    return _normalize(source, template, payload, area.boundary)[0]


def record_rejection(db, *, area_id, label, channel, raw_record, error, row_number=1, filename=None):
    area = area_for_write(db, area_id)
    source, template = _catalog(db, area, label, channel)
    raw = _json(raw_record)
    if not isinstance(raw, dict):
        raw = {'original_record': raw}
    digest = Foundation._hash_json(raw)
    code, message = Foundation._error_parts(error)
    key = Foundation._hash_json({'source': source.id, 'rejected': digest, 'code': code,
                                'row': row_number, 'filename': filename})
    existing = db.query(MapIngestRun).filter_by(idempotency_key=key).first()
    if existing:
        return existing
    plan = {'structure': {'adapter': 'map-feature-adoption-9.1'}, 'counts': {'failed': 1},
        'rows': [{'row_number': row_number, 'classification': 'failed', 'asset_id': None, 'changes': [], 'groups': [],
                  'errors': [{'field': 'row', 'code': code, 'message': message}]}]}
    return _execute(db, source=source, template=template, rows=[(row_number, raw)], plan=plan, file_hash=digest,
        filename=filename or f'{channel}-rejected.json', revision=digest[:20], key=key,
        created_by=db.info.get('principal_user_id'), commit=False)


def adopt(db, payload, *, channel='legacy', target=None, commit=False, provided=None, raw_record=None,
          row_number=1, filename=None):
    area = area_for_write(db, target.operational_area_id if target else payload.get('operational_area_id'))
    original = _json(deepcopy(payload))
    if raw_record is not None:
        original['original_record'] = _json(deepcopy(raw_record))
    label = 'manual' if target is not None else str(payload.get('source') or channel)[:50]
    source, template = _catalog(db, area, label, 'manual' if target is not None else channel)
    incoming, states = _normalize(source, template, payload, area.boundary)
    if target is not None and provided is not None:
        if not set(provided) & {'geometry', 'geometry_type', 'latitude', 'longitude'}:
            states['geometry'] = 'not_provided'
        elif all(key in provided and provided[key] is None for key in ('geometry', 'latitude', 'longitude')):
            states['geometry'] = 'clear'
        for group in ('water_cut', 'production'):
            if not set(provided.get('attributes') or {}) & set(GROUPS[group]):
                states[group] = 'not_provided'
    if target is not None:
        Foundation.record_observed_baseline(db, target)
        if target.operational_area_id is None:
            target.operational_area_id = area.id
        # A by-ID edit has explicit target identity. Its source-local record ID
        # is an internal observation key, never a claimed production identifier.
        incoming['external_id'] = f'asset:{target.id}'
        incoming['canonical_key'] = 'manual-observation:' + str(target.id)
        incoming['verified'] = bool(payload.get('verified'))
        incoming['verification_state'] = 'human_verified' if incoming['verified'] else (target.verification_state or 'unverified')
        FacilityIdentityService.ensure_identity(db, source=source, asset=target, normalized=incoming)
        asset = target
    else:
        # Do not silently attach generic old labels to a registered source.
        query = db.query(JurisdictionAsset).filter_by(external_id=incoming.get('external_id'), source=payload.get('source'))
        if 'authorized_area_ids' not in db.info and db.info.get('principal_user_id') is None:
            from sqlalchemy import or_
            query = query.filter(or_(JurisdictionAsset.operational_area_id == area.id, JurisdictionAsset.operational_area_id.is_(None)))
        else:
            query = query.filter_by(operational_area_id=area.id)
        matches = query.all() if incoming.get('external_id') else []
        if any((row.attributes or {}).get('source_id') not in {None, source.id} for row in matches):
            raise ValueError('asset_identity_namespace_required')
        old = [row for row in matches if not (row.attributes or {}).get('source_id')]
        if len(old) > 1:
            raise ValueError('ambiguous_asset_identity')
        if old:
            Foundation.record_observed_baseline(db, old[0])
            if old[0].operational_area_id is None:
                old[0].operational_area_id = area.id
            FacilityIdentityService.ensure_identity(db, source=source, asset=old[0], normalized=incoming)
        asset, _, _ = resolve_asset(db, source, incoming)
    resolved, groups, changes = group_plan(db, source, template, original, incoming, states, asset)
    if target is not None:
        # Explicit human edits are logged as manual overrides only for provided
        # groups; this does not let generic import labels gain that authority.
        for group in groups:
            if group['state'] == 'not_provided':
                continue
            after = _group_values(incoming, group['group'], template)
            if group['state'] in {'clear', 'unknown', 'withdraw'}:
                after = {key: None for key in after}
            if group['old'] != after:
                _set_values(resolved, group['group'], after)
                group.update(status='accepted', reason='explicit_by_id_manual_edit', manual_override=True, new=after)
                resolved['attributes'].setdefault('field_groups', {})[group['group']] = {
                    'state': group['state'], 'source_id': source.id, 'trust_rank': source.trust_rank, 'manual_override': True}
                changes.append({'field': group['group'], 'group': group['group'], 'old': group['old'], 'new': after})
        for key in ('valid_from', 'valid_to'):
            resolved[key] = incoming.get(key)
    if any(group['group'] == 'geometry' and group['status'] == 'accepted' for group in groups):
        resolved['geometry_type'] = incoming['geometry_type']
    # Description, aliases and operational status are not discarded simply
    # because the older spreadsheet field contract did not model them.
    annotation_before, annotation_after = {}, {}
    for key in (*EXTRAS, 'verification_state'):
        if key in incoming and (target is not None or asset is None or source.id == (asset.attributes or {}).get('source_id')):
            annotation_before[key], annotation_after[key] = resolved.get(key), deepcopy(incoming[key])
            if resolved.get(key) != incoming[key]:
                changes.append({'field': key, 'group': 'details', 'old': resolved.get(key), 'new': incoming[key]})
            resolved[key] = deepcopy(incoming[key])
    for key, value in incoming['attributes'].items():
        if (key not in RESERVED and key not in {field[0] for field in FIELDS}
                and not key.startswith(('original_coordinate_', 'coordinate_transformation'))
                and (target is not None or asset is None or source.id == (asset.attributes or {}).get('source_id'))):
            annotation_before[key], annotation_after[key] = resolved['attributes'].get(key), deepcopy(value)
            if resolved['attributes'].get(key) != value:
                changes.append({'field': key, 'group': 'details', 'old': resolved['attributes'].get(key), 'new': value})
                resolved['attributes'][key] = deepcopy(value)
    if annotation_after:
        groups.append({'group': 'annotations', 'state': 'set', 'status': 'accepted' if annotation_before != annotation_after else 'unchanged',
            'reason': 'explicit_by_id_manual_edit' if target else 'source_observation',
            'old': annotation_before, 'new': annotation_after, 'source_id': source.id,
            'trust_rank': source.trust_rank, 'manual_override': target is not None})
    classification = 'conflict' if any(g['status'] == 'conflict' for g in groups) else 'new' if asset is None else 'updated' if changes else 'unchanged'
    if not incoming.get('external_id') and classification not in {'conflict', 'unchanged'}:
        classification = 'identity_pending'
    entry = {'row_number': row_number, 'classification': classification, 'asset_id': asset.id if asset else None,
        'asset_version': None, 'normalized_payload': incoming, 'resolved_payload': resolved, 'groups': groups,
        'changes': changes, 'errors': [], 'base_hash': Foundation._hash_json(Foundation.asset_to_dict(asset)) if asset else None}
    digest = Foundation._hash_json(original)
    key = Foundation._hash_json({'source': source.id, 'payload': digest, 'target': asset.id if asset else None,
                                'base': entry['base_hash'], 'row': row_number, 'filename': filename})
    existing_run = db.query(MapIngestRun).filter_by(idempotency_key=key).first()
    if existing_run is not None:
        claim = db.query(MapFeatureClaim).filter_by(run_id=existing_run.id).one()
        asset = db.get(JurisdictionAsset, claim.asset_id)
        asset._compat_receipt = {'run_id': existing_run.id, 'updated': 0, 'reused': True}
        return asset, False
    run = _execute(db, source=source, template=template, rows=[(row_number, original)],
        plan={'structure': {'adapter': 'map-feature-adoption-9.1', 'headers': sorted(original)},
              'counts': {classification: 1}, 'rows': [entry]}, file_hash=digest, filename=filename or f'{channel}-observation.json',
        revision=digest[:20], key=key, created_by=db.info.get('principal_user_id'), commit=commit)
    claim = db.query(MapFeatureClaim).filter_by(run_id=run.id).one()
    asset = db.get(JurisdictionAsset, claim.asset_id)
    asset._compat_receipt = {'run_id': run.id, 'updated': run.updated_assets, 'reused': False}
    return asset, bool(run.created_assets)
