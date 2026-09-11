"""Road access reference from explicitly registered origins to frozen well points.

Consumes the existing permission-bound Valhalla service. It does not claim that
a camera can dispatch a vehicle or that snapping proves a facility entrance.
"""
import math
import time
from datetime import datetime
from pathlib import Path

from app.services.road_access_policy import VehicleAssumption
from app.services.road_calculation_service import calculate_distance_matrix
from app.services.road_network_service import select_network, resolve_network, recheck_network
from app.services.spatial_coverage_service import read_comparison, _valid_target
from app.services.vehicle_router import ENGINE_VERSION, RoadLocation, RoadCalculationError


def compare_coverage_roads(db, comparison_id: str, *, at: datetime, vehicle: VehicleAssumption,
                           distance_budget_m: float, artifact_root: Path, cancel_event=None,
                           network_id: str | None = None):
    if (type(distance_budget_m) not in (int, float) or not math.isfinite(distance_budget_m)
            or not 0 < distance_budget_m <= 50000):
        raise ValueError('coverage_road_budget_invalid')
    saved = read_comparison(db, comparison_id, now=at)
    if saved['freshness'] != 'unchanged_inputs':
        raise ValueError('coverage_source_changed')
    frozen = saved['input_snapshot']
    def origin_eligible(row):
        if not (row['asset_type'] == 'checkpoint' and row.get('road_reference_origin') is True
                and row['status'] == 'active' and _valid_target(row, at)
                and row['operational_status'] == 'online'):
            return False
        try:
            expiry = datetime.fromisoformat(row['operational_status_valid_until'])
            return expiry.utcoffset() is not None and expiry > at
        except (TypeError, ValueError):
            return False

    origins = [row for row in frozen['resources'] if origin_eligible(row) and abs(row['latitude']) <= 85]
    targets = [row for row in frozen['targets'] if _valid_target(row, at) and abs(row['latitude']) <= 85]
    excluded = set(frozen['disabled_resource_ids'])
    moved = set(map(int, frozen['movements']))
    # Moving a display device is not proof of a new road entrance; do not snap
    # an arbitrary proposed coordinate through a fence or onto a bridge.
    scenario_origins = [row for row in origins if row['id'] not in excluded | moved]
    result = {'schema_version': 'coverage-road-reference-4.4-1', 'comparison_id': comparison_id,
        'coverage_input_digest': saved['input_digest'], 'analysis_at': at.isoformat(),
        'vehicle': vehicle.model_dump(), 'distance_budget_m': distance_budget_m,
        'state': 'information_missing', 'matrix_batches': [], 'targets': [],
        'information_gaps': [], 'execution_task_created': False,
        'boundary': '仅比较明确登记机动车参考出发点至井点附近道路的距离，不确认井场入口、实际车辆驻点、完整空间覆盖或防控效果。时间基于静态道路速度假设。'}
    if not origins:
        result['information_gaps'].append('缺少有效且明确登记的机动车参考出发点，不把摄像头或照明设备当成车辆出发点。')
        return result
    if not targets:
        result['information_gaps'].append('没有可用于道路关联的核验井点，不用区域中心代替。')
        return result
    if len(origins) > 10:
        raise ValueError('coverage_road_background_batch_required')
    if len(targets) != len(frozen['targets']):
        result['information_gaps'].append('部分登记井坐标或有效期不适用，未计算道路关联。')
    if moved:
        result['information_gaps'].append('移动假设没有可信道路接入证明，对应方案出发点保留未知，不从任意新坐标自动接路。')
    binding = (select_network(db, analysis_at=at, vehicle=vehicle, engine_version=ENGINE_VERSION)
               if network_id is None else resolve_network(db, network_id, analysis_at=at, vehicle=vehicle))
    deadline = time.monotonic() + 120
    for offset in range(0, len(targets), 10):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RoadCalculationError('road_calculation_timeout')
        batch = targets[offset:offset + 10]
        matrix = calculate_distance_matrix(db, network_id=binding.network_id, analysis_at=at,
            sources=[RoadLocation(latitude=float(row['latitude']), longitude=float(row['longitude'])) for row in origins],
            targets=[RoadLocation(latitude=float(row['latitude']), longitude=float(row['longitude'])) for row in batch],
            vehicle=vehicle, artifact_root=artifact_root, cancel_event=cancel_event, timeout_seconds=remaining)
        if matrix['graph_sha256'] != binding.graph_sha256 or matrix['policy_revision'] != binding.policy_revision:
            raise RoadCalculationError('coverage_road_network_changed')
        result['matrix_batches'].append(matrix)
        for index, target in enumerate(batch):
            candidates = [cell for cell in matrix['cells'] if cell['target_index'] == index]
            within = [origins[cell['source_index']]['id'] for cell in candidates
                      if cell['status'] == 'calculated' and cell['distance_m'] <= distance_budget_m]
            result['targets'].append({'target_id': target['id'], 'baseline_origin_ids_within_budget': within,
                'scenario_origin_ids_within_budget': [identifier for identifier in within
                                                     if identifier in {row['id'] for row in scenario_origins}],
                'scenario_connection_unknown': bool(moved & {row['id'] for row in origins}),
                'boundary': '未找到路径不等于现实不可达；不存在参考出发点不等于没有处置能力。'})
    recheck_network(db, binding, analysis_at=at, vehicle=vehicle)
    if read_comparison(db, comparison_id, now=at)['freshness'] != 'unchanged_inputs':
        raise ValueError('coverage_source_changed')
    result.update(state='calculated_reference', network_id=binding.network_id,
                  graph_sha256=binding.graph_sha256, policy_revision=binding.policy_revision)
    return result
