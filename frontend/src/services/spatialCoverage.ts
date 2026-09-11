import api from './api'
import type { FeatureCollection } from 'geojson'

export type CoverageSummary = {
  area_coverage?: {
    state: string; boundary: string; boundary_kind?: string; information_gaps: string[]
    boundary_area_m2?: number; known_covered_area_m2?: number; unique_overlap_area_m2?: number
    outside_known_coverage_area_m2?: number; uncovered_area_m2?: number | null
    map_geometry?: FeatureCollection
  }
  target_count: number
  covered_count: number
  overlap_count: number
  unknown_count: number
  outside_known_count: number
  resources: { resource_id: number; state: string }[]
  targets: { target_id: number; state: string; covered_by: number[] }[]
}

export type CoverageResult = {
  id: string
  baseline: CoverageSummary
  scenario: CoverageSummary
  boundary: string
  algorithm_version: string
  input_digest: string
  input_snapshot: { area_id: number; as_of: string; map_snapshot_id?: string | null; resources: { id: number; latitude: number | null; longitude: number | null }[] }
  historical?: boolean
  freshness?: string
  history_boundary?: string
  persisted: boolean
}

export type CoverageScenario = {
  disabled_resource_ids: number[]
  movements: { resource_id: number; latitude: number; longitude: number }[]
}

export const spatialCoverageApi = {
  list: async (page: number) => (
    await api.get<{ items: { id: string; operational_area_id: number; created_at: string }[]; total: number }>(
      '/deployment-sandbox/spatial-comparisons', { params: { page, page_size: 10 } })
  ).data,
  compare: async (scenario: CoverageScenario): Promise<CoverageResult> => (
    await api.post<CoverageResult>('/deployment-sandbox/spatial-compare', scenario)
  ).data,
  get: async (id: string): Promise<CoverageResult> => (
    await api.get<CoverageResult>(`/deployment-sandbox/spatial-comparisons/${encodeURIComponent(id)}`)
  ).data,
}

export type CoverageRoadJob = {
  event_id: string
  status: string
  artifact: null | {
    state: string
    boundary: string
    distance_budget_m: number
    information_gaps: string[]
    network_id?: string
    graph_sha256?: string
    targets: { target_id: number; baseline_origin_ids_within_budget: number[];
      scenario_origin_ids_within_budget: number[]; scenario_connection_unknown: boolean }[]
  }
}

export const coverageRoadApi = {
  list: async (comparisonId: string, page: number) => (
    await api.get<{ items: { event_id: string; status: string; created_at: string }[]; total: number }>(
      `/deployment-sandbox/spatial-comparisons/${encodeURIComponent(comparisonId)}/road-jobs`,
      { params: { page, page_size: 10 } })
  ).data,
  start: async (comparisonId: string, budget: number, vehicle: { kind: 'auto' | 'truck'; height_m?: number; weight_t?: number }) => (
    await api.post<{ event_id: string }>(`/deployment-sandbox/spatial-comparisons/${encodeURIComponent(comparisonId)}/road-jobs`, {
      vehicle: { ...vehicle, source: 'explicit_reference_assumption' }, distance_budget_m: budget,
    })
  ).data,
  get: async (id: string): Promise<CoverageRoadJob> => (
    await api.get<CoverageRoadJob>(`/deployment-sandbox/road-jobs/${encodeURIComponent(id)}`)
  ).data,
  cancel: async (id: string) => (
    await api.post<{ status: string }>(`/deployment-sandbox/road-jobs/${encodeURIComponent(id)}/cancel`)
  ).data,
}
