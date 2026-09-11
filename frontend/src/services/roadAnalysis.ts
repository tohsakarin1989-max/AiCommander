import api from './api'

export interface RoadVehicle {
  kind: 'auto' | 'truck'
  source: 'case_record' | 'explicit_reference_assumption'
  height_m?: number | null
  weight_t?: number | null
}

export function roadVehicleLabel(vehicle?: RoadVehicle): string {
  if (!vehicle) return '历史成果未记录车型条件，不能据此确认车辆可通行'
  const origin = vehicle.source === 'case_record' ? '案件记录' : '参考假设，非案件事实'
  if (vehicle.kind === 'auto') return `小客车（${origin}）`
  return `货车（${origin}）；车高 ${vehicle.height_m ?? '未记录'} 米，总重 ${vehicle.weight_t ?? '未记录'} 吨`
}

export interface CaseRoadComparison {
  schema_version: 'case-road-comparison-4.2.0-1'
  result_id: string
  content_sha256: string
  map_snapshot_id: string | null
  targets: Array<{ asset_id: number; name: string; candidate_id: string; evidence_ref: string }>
  information_gaps: string[]
  boundary: string
  matrix: null | {
    network_id: string; graph_sha256: string; policy_revision: number; analysis_at: string
    vehicle?: RoadVehicle
    cells: Array<{ source_index: number; target_index: number; status: string; distance_m?: number | null }>
  }
}

export interface RoadDetourReference {
  basis: 'route_geometry_endpoints'; status: 'available' | 'endpoints_too_close' | 'rounding_limited'
  straight_distance_m: number; road_distance_m: number; ratio: number | null; additional_distance_m: number | null
}

export function roadDetourLabel(value?: RoadDetourReference): string {
  if (!value) return '历史结果未记录绕行基准。'
  if (value.status === 'endpoints_too_close') return '道路起终点相距不足 10 米，不计算容易失真的绕行倍数。'
  if (value.status !== 'available' || value.basis !== 'route_geometry_endpoints'
      || typeof value.ratio !== 'number' || !Number.isFinite(value.ratio) || value.ratio < 1
      || typeof value.additional_distance_m !== 'number' || !Number.isFinite(value.additional_distance_m)
      || value.additional_distance_m < 0 || !Number.isFinite(value.straight_distance_m))
    return '精度或基准不足，暂不显示绕行倍数。'
  return `道路端点直线距离 ${(value.straight_distance_m / 1000).toFixed(2)} 公里；沿路为其 ${value.ratio.toFixed(2)} 倍，多行 ${(value.additional_distance_m / 1000).toFixed(2)} 公里。`
}

export interface CaseRoadRoute {
  schema_version: 'case-road-route-4.2.0-1'; result_id: string; content_sha256: string
  map_snapshot_id: string; target: { asset_id: number; name: string }; boundary: string
  route: { shape_polyline6: string; network_id: string; graph_sha256: string; distance_m: number; analysis_at: string
    detour_reference?: RoadDetourReference
    alternatives?: Array<{ shape_polyline6: string; distance_m: number; reference_time_seconds: number; way_ids: number[]; detour_reference?: RoadDetourReference }>
    alternatives_status?: 'available' | 'no_distinct_alternative_returned'
  }
}

export type RoadArtifactSummary = { id: string; availability: 'unavailable' } | {
  id: string; availability: 'available'; operation: 'comparison' | 'route'; created_at: string; content_sha256: string
}
export interface RoadArtifact {
  id: string; created_at: string; content_sha256: string; content: CaseRoadComparison | CaseRoadRoute
}

export interface AutomaticRoadComparison {
  result_id: string; content_sha256: string
  status: 'processing' | 'waiting_network' | 'completed' | 'information_missing' | 'unavailable' | 'not_available'
  artifact: (RoadArtifact & { content: CaseRoadComparison }) | null
}

export type RoadBudget = { metric: 'distance'; distance_m: number } | { metric: 'time'; seconds: number }
export interface CaseReachableRoads {
  result_id: string; content_sha256: string; map_snapshot_id: string
  schema_version: 'case-reachable-roads-4.2.0-1'; metric: 'distance' | 'time'; budget: number
  boundary: string; information_gaps: string[]
  reachability: null | {
    graph_sha256: string; network_id: string; analysis_at: string
    native_completion_contract: 'completed-v1'; vehicle: RoadVehicle
    roads: { type: 'FeatureCollection'; features: Array<{
      type: 'Feature'; geometry: { type: 'LineString'; coordinates: Array<[number, number]> }
    }> }
  }
}

export async function caseReachableRoads(comparison: CaseRoadComparison, budget: RoadBudget,
  signal: AbortSignal): Promise<{ data: CaseReachableRoads; segments: Array<Array<[number, number]>> }> {
  const matrix = comparison.matrix
  if (!matrix || !comparison.map_snapshot_id) throw new Error('缺少冻结道路比较依据')
  const { data } = await api.post<CaseReachableRoads>(
    `/road-analysis/case-results/${encodeURIComponent(comparison.result_id)}/reachable-roads`, {
      ...budget, content_sha256: comparison.content_sha256, network_id: matrix.network_id,
      graph_sha256: matrix.graph_sha256, analysis_at: matrix.analysis_at,
    }, { signal })
  if (data.schema_version !== 'case-reachable-roads-4.2.0-1' || data.result_id !== comparison.result_id
      || data.content_sha256 !== comparison.content_sha256 || data.map_snapshot_id !== comparison.map_snapshot_id
      || data.metric !== budget.metric || data.budget !== ('distance_m' in budget ? budget.distance_m : budget.seconds)
      || typeof data.boundary !== 'string' || !Array.isArray(data.information_gaps)
      || data.information_gaps.some(item => typeof item !== 'string')) throw new Error('预算道路版本不一致')
  if (data.reachability === null) return { data, segments: [] }
  const result = data.reachability
  if (!result || result.native_completion_contract !== 'completed-v1' || result.network_id !== matrix.network_id
      || result.graph_sha256 !== matrix.graph_sha256 || result.analysis_at !== matrix.analysis_at
      || result.roads?.type !== 'FeatureCollection' || !Array.isArray(result.roads.features)
      || result.roads.features.length > 10000) throw new Error('预算道路计算未完成或版本变化')
  let vertices = 0
  const segments = result.roads.features.map(feature => {
    const points = feature.geometry?.coordinates
    if (feature.type !== 'Feature' || feature.geometry?.type !== 'LineString'
        || !Array.isArray(points) || points.length < 2 || (vertices += points.length) > 200000)
      throw new Error('预算道路几何无效')
    return points.map((point): [number, number] => {
      if (!Array.isArray(point) || point.length !== 2 || point.some(value => typeof value !== 'number' || !Number.isFinite(value))
          || Math.abs(point[0]) > 180 || Math.abs(point[1]) > 85) throw new Error('预算道路坐标无效')
      return [point[1], point[0]]
    })
  })
  return { data, segments }
}

export async function readAutomaticRoadComparison(resultId: string, hash: string, signal: AbortSignal): Promise<AutomaticRoadComparison> {
  const { data } = await api.get<AutomaticRoadComparison>(
    `/road-analysis/case-results/${encodeURIComponent(resultId)}/automatic-comparison`, { signal })
  if (data.result_id !== resultId || data.content_sha256 !== hash
      || !['processing', 'waiting_network', 'completed', 'information_missing', 'unavailable', 'not_available'].includes(data.status)) {
    throw new Error('自动道路成果版本不一致')
  }
  if (data.status === 'completed') {
    const content = data.artifact?.content
    if (!data.artifact || typeof data.artifact.id !== 'string' || !data.artifact.id.trim()
        || typeof data.artifact.content_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(data.artifact.content_sha256)
        || !content || content.schema_version !== 'case-road-comparison-4.2.0-1'
        || content.result_id !== resultId || content.content_sha256 !== hash || !content.matrix
        || !Array.isArray(content.targets) || content.targets.length > 3 || !Array.isArray(content.information_gaps)) {
      throw new Error('自动道路成果内容不完整')
    }
  } else if (data.artifact !== null) {
    throw new Error('未完成任务不能携带道路成果')
  }
  return data
}

export async function roadArtifactHistory(resultId: string, signal: AbortSignal, beforeId?: string): Promise<{
  items: RoadArtifactSummary[]; next_before_id: string | null
}> {
  const { data } = await api.get(`/road-analysis/case-results/${encodeURIComponent(resultId)}/artifacts`, {
    params: { limit: 10, before_id: beforeId }, signal,
  })
  return data
}

export async function readRoadArtifact(id: string, resultId: string, hash: string, signal: AbortSignal): Promise<RoadArtifact> {
  const { data } = await api.get<RoadArtifact>(`/road-analysis/artifacts/${encodeURIComponent(id)}`, { signal })
  if (data.id !== id || data.content_sha256 !== hash || data.content.result_id !== resultId
      || !['case-road-comparison-4.2.0-1', 'case-road-route-4.2.0-1'].includes(data.content.schema_version)) {
    throw new Error('历史道路成果引用不一致，请重新读取列表')
  }
  return data
}

export async function expandCaseRoad(comparison: CaseRoadComparison, assetId: number, signal: AbortSignal): Promise<CaseRoadRoute> {
  const matrix = comparison.matrix
  if (!matrix || !comparison.targets.some(target => target.asset_id === assetId)) throw new Error('缺少道路比较依据')
  const { data } = await api.post<CaseRoadRoute>(`/road-analysis/case-results/${encodeURIComponent(comparison.result_id)}/routes/${assetId}`, {
    network_id: matrix.network_id, graph_sha256: matrix.graph_sha256,
    analysis_at: matrix.analysis_at, content_sha256: comparison.content_sha256,
  }, { signal })
  if (data.schema_version !== 'case-road-route-4.2.0-1' || data.result_id !== comparison.result_id
      || data.content_sha256 !== comparison.content_sha256 || data.target.asset_id !== assetId
      || data.map_snapshot_id !== comparison.map_snapshot_id || data.route.network_id !== matrix.network_id
      || data.route.graph_sha256 !== matrix.graph_sha256 || data.route.analysis_at !== matrix.analysis_at) throw new Error('路径版本发生变化，请重新比较')
  return data
}

export async function compareCaseRoads(resultId: string, hash: string, signal: AbortSignal): Promise<CaseRoadComparison> {
  const { data } = await api.post<CaseRoadComparison>(
    `/road-analysis/case-results/${encodeURIComponent(resultId)}/comparison`, undefined, { signal },
  )
  if (data.schema_version !== 'case-road-comparison-4.2.0-1' || data.result_id !== resultId
      || data.content_sha256 !== hash || !Array.isArray(data.targets) || data.targets.length > 3
      || !Array.isArray(data.information_gaps)) throw new Error('道路比较引用版本不一致，请刷新成果。')
  return data
}
