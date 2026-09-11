"""Automatic comparison of frozen evidence points, never inferred region centres."""
from app.services.case_result_map import load_result_map_context
from app.services.case_result_service import CaseResultService
from app.services.road_calculation_service import (calculate_distance_matrix, calculate_reference_route,
    calculate_distance_reachability, calculate_time_reachability)
from app.services.road_network_service import resolve_network
from app.services.vehicle_router import RoadLocation, RoadCalculationError


def _comparison_inputs(db, result_id):
    context = load_result_map_context(db, result_id)
    spec = context['map']
    marker = spec['case_marker']
    gaps, targets, seen = [], [], set()
    features = {item['properties']['asset_id']: item for item in (context['production'] or {}).get('features', [])}
    snapshot = spec['map_snapshot_id']
    for candidate in sorted(spec['candidates'], key=lambda value: value['rank'])[:3]:
        for reference in candidate['evidence_refs']:
            for asset_id, feature in features.items():
                if reference != f'map_asset:{asset_id}@snapshot:{snapshot}' or asset_id in seen:
                    continue
                geometry = feature.get('geometry') or {}
                coordinates = geometry.get('coordinates')
                if geometry.get('type') != 'Point' or not isinstance(coordinates, list) or len(coordinates) != 2:
                    gaps.append(f"{candidate['title']}缺少可用设施点位，不以区域中心代替。")
                    continue
                try:
                    point = RoadLocation(longitude=coordinates[0], latitude=coordinates[1])
                except ValueError:
                    gaps.append(f"{candidate['title']}的坐标待核验。")
                    continue
                seen.add(asset_id)
                targets.append({'asset_id': asset_id, 'name': feature['properties']['name'],
                    'candidate_id': candidate['id'], 'evidence_ref': reference, 'point': point.model_dump()})
                break
            if len(targets) >= 3:
                break
        if len(targets) >= 3:
            break
    result = {'schema_version': 'case-road-comparison-4.2.0-1', 'result_id': result_id,
        'content_sha256': context['content_sha256'], 'map_snapshot_id': snapshot,
        'targets': targets, 'information_gaps': gaps, 'matrix': None,
        'boundary': '以当前已知通行条件比较冻结点位附近的道路，不还原案发时路况，不确认设施入口或实际轨迹。'}
    return context, result, marker


def compare_result_roads(db, *, result_id, analysis_at, vehicle, artifact_root, cancel_event=None,
                         network_id=None):
    context, result, marker = _comparison_inputs(db, result_id)
    targets, gaps = result['targets'], result['information_gaps']
    if not marker or not targets:
        gaps.append('缺少案件坐标或带固定地图引用的设施点位，暂不计算道路距离。')
        return result
    matrix = calculate_distance_matrix(db, network_id=network_id, analysis_at=analysis_at,
        sources=[RoadLocation(longitude=marker['longitude'], latitude=marker['latitude'])],
        targets=[RoadLocation(**item['point']) for item in targets], vehicle=vehicle,
        artifact_root=artifact_root, cancel_event=cancel_event)
    current = CaseResultService.read(db, result_id)
    if current['content_sha256'] != context['content_sha256']:
        raise ValueError('road_result_source_changed')
    result['matrix'] = matrix
    return result


def route_result_target(db, *, result_id, asset_id, network_id, graph_sha256, content_sha256,
                        analysis_at, vehicle, artifact_root, cancel_event=None):
    context, result, marker = _comparison_inputs(db, result_id)
    if context['content_sha256'] != content_sha256:
        raise ValueError('road_result_source_changed')
    target = next((item for item in result['targets'] if item['asset_id'] == asset_id), None)
    if marker is None or target is None:
        raise ValueError('road_result_target_unavailable')
    # Bind route expansion to the comparison graph, not a newly selected graph.
    binding = resolve_network(db, network_id, analysis_at=analysis_at, vehicle=vehicle)
    if binding.graph_sha256 != graph_sha256:
        raise ValueError('road_result_network_changed')
    route = calculate_reference_route(db, network_id=network_id, analysis_at=analysis_at,
        start=RoadLocation(longitude=marker['longitude'], latitude=marker['latitude']),
        end=RoadLocation(**target['point']), vehicle=vehicle, artifact_root=artifact_root,
        cancel_event=cancel_event)
    if (route['graph_sha256'] != graph_sha256
            or CaseResultService.read(db, result_id)['content_sha256'] != content_sha256):
        raise ValueError('road_result_source_changed')
    return {'schema_version': 'case-road-route-4.2.0-1', 'result_id': result_id,
            'content_sha256': content_sha256, 'map_snapshot_id': result['map_snapshot_id'],
            'target': target, 'boundary': result['boundary'], 'route': route}


def reachable_result_roads(db, *, result_id, network_id, graph_sha256, content_sha256,
                           analysis_at, vehicle, artifact_root, metric, budget, cancel_event=None):
    """Use only the frozen case marker, retaining the comparison's graph binding."""
    context = load_result_map_context(db, result_id)
    if context['content_sha256'] != content_sha256:
        raise ValueError('road_result_source_changed')
    marker = context['map']['case_marker']
    result = {'schema_version': 'case-reachable-roads-4.2.0-1', 'result_id': result_id,
              'content_sha256': content_sha256, 'map_snapshot_id': context['map']['map_snapshot_id'],
              'metric': metric, 'budget': budget, 'reachability': None, 'information_gaps': [],
              'boundary': '仅表示冻结案件点位在已知通行条件下的预算道路段参考，不代表完整区域覆盖、实际轨迹或案发时通行状态。'}
    if marker is None:
        result['information_gaps'].append('冻结案件成果缺少坐标，未以候选区域中心替代。')
        return result
    binding = resolve_network(db, network_id, analysis_at=analysis_at, vehicle=vehicle)
    if binding.graph_sha256 != graph_sha256:
        raise ValueError('road_result_network_changed')
    if metric not in ('distance', 'time'):
        raise ValueError('road_reachability_budget_invalid')
    calculate = calculate_distance_reachability if metric == 'distance' else calculate_time_reachability
    value = calculate(db, network_id=network_id, analysis_at=analysis_at, vehicle=vehicle,
        origin=RoadLocation(longitude=marker['longitude'], latitude=marker['latitude']),
        artifact_root=artifact_root, cancel_event=cancel_event,
        **({'distance_m': budget} if metric == 'distance' else {'seconds': budget}))
    if value.get('native_completion_contract') != 'completed-v1':
        raise RoadCalculationError('road_engine_completion_required')
    if (value['graph_sha256'] != graph_sha256
            or CaseResultService.read(db, result_id)['content_sha256'] != content_sha256):
        raise ValueError('road_result_source_changed')
    result['reachability'] = value
    return result
