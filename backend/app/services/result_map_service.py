"""Same frozen points and offline basemap for the reader and material export."""
from dataclasses import replace
import json
import re

from app.services.case_result_document import DocumentBlock
from app.services.case_result_map import _coordinate


def _query_map(body):
    """Read the answer's frozen map, never resolve live objects or a new map."""
    result = body.get('result') or {}
    answer = result.get('answer') or {}
    context = answer.get('map_context')
    if answer.get('schema_version') != 'business-answer-8.4-1' or context is None:
        return {'state': 'not_applicable', 'reason': '此历史查询未冻结地图上下文，未用当前地图补齐。'}
    invalid = {'state': 'unavailable', 'reason': '答案地图引用或点位不完整，未重新查询或猜测位置。'}
    cards = [card.get('data', {}).get('map_context') for card in result.get('cards', [])
             if card.get('data', {}).get('map_context') is not None]
    if (not isinstance(context, dict) or not cards or any(value != context for value in cards)
            or context.get('schema_version') != 'business-answer-map-8.4-1'
            or context.get('state') not in {'ready', 'partial', 'unavailable'}):
        return invalid
    points, snapshots = context.get('points'), context.get('snapshots')
    gaps, coverage = context.get('information_gaps'), context.get('coverage')
    if (not isinstance(points, list) or len(points) > 100 or not isinstance(snapshots, list)
            or not isinstance(gaps, list) or any(not isinstance(value, str) for value in gaps)
            or not isinstance(coverage, dict) or coverage.get('shown') != len(points)
            or coverage.get('point_limit') != 100 or type(coverage.get('truncated')) is not bool
            or not isinstance(context.get('boundary'), str)):
        return invalid
    identifiers = []
    for snapshot in snapshots:
        identifier = snapshot.get('id') if isinstance(snapshot, dict) else None
        if (not isinstance(identifier, str) or identifier == 'current'
                or re.fullmatch(r'[A-Za-z0-9_-]{1,36}', identifier) is None or identifier in identifiers):
            return invalid
        identifiers.append(identifier)
    mapped = []
    roles = {'discovery': '发现／查获地点', 'incident': '有依据的案发地点', 'facility': '设施冻结点位'}
    for point in points:
        if (not isinstance(point, dict) or point.get('map_snapshot_id') not in identifiers
                or point.get('kind') not in {'case', 'asset'} or type(point.get('object_id')) is not int
                or point['object_id'] <= 0 or not isinstance(point.get('label'), str)
                or point.get('role') not in ({'discovery', 'incident'} if point['kind'] == 'case' else {'facility'})
                or not _coordinate(point.get('longitude'), 180) or not _coordinate(point.get('latitude'), 85)
                or not isinstance(point.get('evidence_refs'), list) or not point['evidence_refs']
                or any(not isinstance(ref, str) for ref in point['evidence_refs'])):
            return invalid
        mapped.append({'longitude': point['longitude'], 'latitude': point['latitude'],
            'label': f"{point['label']}（{roles[point['role']]}）",
            'point_kind': 'facility' if point['kind'] == 'asset' else 'case',
            'object_id': point['object_id'], 'role': point['role'], 'evidence_refs': list(point['evidence_refs'])})
    warnings = [*gaps, context['boundary']]
    if len(identifiers) != 1:
        return {'state': 'unavailable', 'reason': '答案涉及多个或未绑定底图版本，未将不同历史快照合成一张地图，也不用当前地图替代。',
                'warnings': warnings}
    if context['state'] == 'unavailable' or not mapped:
        return {'state': 'unavailable', 'reason': '答案未冻结可用的明确点位，文字回答仍可使用。', 'warnings': warnings}
    return {'state': 'available', 'schema': 'business-material-map-6.5-1',
        'source_schema': context['schema_version'], 'data_state': context['state'],
        'map_snapshot_id': identifiers[0], 'points': mapped, 'point_count': len(mapped),
        'warnings': warnings, 'case_marker': None, 'candidates': [], 'production_asset_ids': []}


def frozen_map(envelope):
    kind, body = envelope['kind'], envelope['body']
    points, snapshots, warnings = [], [], []
    if kind == 'query':
        return _query_map(body)
    if kind == 'facility':
        snapshots = [item['id'] for item in body['versions'].get('map_snapshots', [])]
        points.append({**body['facility'], 'label': body['facility']['name'], 'point_kind': 'facility'})
        for section in ('nearby_cases', 'events'):
            items = body['sections'].get(section, {}).get('items', [])
            for item in items:
                points.append({**item, 'label': f"{section} #{item.get('id', item.get('case_id', ''))}",
                               'point_kind': 'case' if section == 'nearby_cases' else 'event'})
        warnings.append('设施、邻近案件及独立事件分层记录；邻近不代表涉案，不推测实际路线。')
    elif kind == 'topic':
        view = body['views']['map']
        snapshots = [item['id'] for item in view['versions']]
        points = [{**point, 'label': f"案件 #{point['case_id']}", 'point_kind': 'case'} for point in view['points']]
        warnings.append('地图仅展示冻结专题首 100 条成员中有坐标的记录，不代表全量案件分布或实际轨迹。')
        warnings.append(f"该页缺少坐标记录：{view['unmapped_in_page']} 条。")
    else:
        return {'state': 'not_applicable', 'reason': '此类材料地图请从冻结来源打开。'}
    mapped = []
    for point in points:
        if _coordinate(point.get('longitude'), 180) and _coordinate(point.get('latitude'), 85):
            mapped.append({key: point[key] for key in ('longitude', 'latitude', 'label', 'point_kind')})
    if len(mapped) > 201:
        raise ValueError('material_map_point_budget_exceeded')
    if len(set(snapshots)) != 1:
        return {'state': 'unavailable', 'reason': '未绑定唯一冻结底图，不用当前地图替代历史版本。'}
    if not mapped:
        return {'state': 'unavailable', 'reason': '冻结材料无有效坐标，不推测位置。'}
    return {'state': 'available', 'schema': 'business-material-map-6.5-1',
        'map_snapshot_id': snapshots[0], 'points': mapped, 'point_count': len(mapped),
        'warnings': warnings, 'case_marker': None, 'candidates': [], 'production_asset_ids': []}


def attach_map(envelope, document):
    if envelope['kind'] not in {'facility', 'topic', 'query'}:
        return document
    spec = frozen_map(envelope)
    if envelope['kind'] == 'query' and spec['state'] == 'not_applicable':
        return document
    metadata = {key: value for key, value in spec.items() if key not in {'points', 'candidates', 'production_asset_ids', 'case_marker'}}
    if spec['state'] == 'available':
        path = f"/api/results/{envelope['kind']}/{envelope['id']}"
        metadata.update(image_url=path + '/map.png', context_url=path + '/map')
        document = replace(document, blocks=document.blocks + (DocumentBlock('map', json.dumps(spec, ensure_ascii=False)),))
    elif envelope['kind'] == 'query':
        document = replace(document, blocks=document.blocks + (DocumentBlock('paragraph', '地图说明：' + spec['reason']),))
    envelope['map'] = metadata
    return document


def map_context(db, kind, identifier):
    from app.services.result_catalog import _read
    from app.services.intelligent_query_tasks import _identity
    from app.services.offline_map_service import OfflineMapService
    _identity(db)
    envelope, _ = _read(db, kind, identifier)
    spec = frozen_map(envelope)
    if spec['state'] != 'available':
        raise ValueError('material_map_unavailable')
    snapshot = OfflineMapService.resolve_snapshot(db, spec['map_snapshot_id'])
    if snapshot.id != spec['map_snapshot_id']:
        raise PermissionError('material_map_version_changed')
    manifest = OfflineMapService.resolved_manifest(db, snapshot)
    basemap = {key: manifest[key] for key in ('snapshot_id', 'version', 'renderer', 'style_url', 'tile_url',
        'bounds', 'min_zoom', 'max_zoom', 'display_max_zoom', 'attribution', 'network_required') if key in manifest}
    return {'result_id': identifier, 'content_sha256': envelope['content_sha256'], 'map': spec, 'basemap': basemap,
        'production': {'type': 'FeatureCollection', 'features': [{'type': 'Feature',
            'properties': {'report_kind': point['point_kind'], 'label': point['label'],
                           **{key: point[key] for key in ('object_id', 'role', 'evidence_refs') if key in point}},
            'geometry': {'type': 'Point', 'coordinates': [point['longitude'], point['latitude']]}}
            for point in spec['points']]}}


def render_material_map(db, kind, identifier):
    from app.services.case_map_image import _render, SLOTS, CaseMapImageError
    from app.services.case_map_render_resources import CaseMapRenderResources
    from app.services.result_catalog import _read
    from app.services.intelligent_query_tasks import _identity
    context = map_context(db, kind, identifier)
    def reader():
        _identity(db)
        return _read(db, kind, identifier)[0]
    resources = CaseMapRenderResources(db, identifier, material_reader=reader,
        snapshot_id=context['map']['map_snapshot_id'])
    if len(json.dumps(context, ensure_ascii=False).encode()) > 2 * 1024 * 1024:
        raise CaseMapImageError('map_render_input_too_large')
    if not SLOTS.acquire(blocking=False):
        raise CaseMapImageError('map_renderer_busy')
    try:
        return _render(db, context, resources, material_reader=reader)
    finally:
        SLOTS.release()
