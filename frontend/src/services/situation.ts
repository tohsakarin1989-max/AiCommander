import api from './api'


export type ChangeDirection = 'rising' | 'falling' | 'stable'
export type AttentionLevel = 'high' | 'medium' | 'low'

export interface SituationWindow {
  days: number
  current_start: string
  current_end: string
  previous_start: string
  previous_end: string
  area_keyword: string | null
}

export interface SituationSummary {
  current_case_count: number
  previous_case_count: number
  case_delta: number
  case_delta_percent: number
  change_direction: ChangeDirection
  geocoded_case_count: number
  data_readiness_percent: number
  hotspot_count: number
  well_attention_count: number
  analysis_status: 'ready' | 'no_current_data'
  source_truncated?: boolean
}

export interface SituationTimelinePoint {
  date: string
  period: 'previous' | 'current'
  count: number
}

export interface PatternShift {
  name: string
  current_count: number
  previous_count: number
  delta: number
  direction: ChangeDirection
}

export interface SituationCasePoint {
  id: number
  case_number: string
  occurred_time: string
  location: string
  case_type: string
  modus_operandi: string
  latitude: number
  longitude: number
}

export interface SituationHotspot {
  id: string
  label: string
  center: { latitude: number; longitude: number }
  case_count: number
  previous_case_count: number
  case_delta: number
  case_ids: number[]
  case_numbers: string[]
  dominant_case_type: string
  dominant_modus_operandi: string
  latest_case_at: string
  radius_km: number
  boundary: string
}

export interface WellAttention {
  asset_id: number
  name: string
  latitude: number
  longitude: number
  verified: boolean
  is_high_production: boolean
  region: string
  nearby_case_count: number
  previous_nearby_case_count: number
  case_delta: number
  minimum_distance_km: number
  latest_case_at: string
  case_ids: number[]
  attention_score: number
  attention_level: AttentionLevel
  reasons: string[]
  boundary: string
}

export interface SituationPriority {
  id: string
  rank: number
  type: 'hotspot_change' | 'well_attention' | 'modus_change' | 'window_change'
  level: AttentionLevel
  title: string
  finding: string
  action: string
  evidence_refs: string[]
  map_focus: { latitude: number; longitude: number } | null
  boundary: string
}

export interface SituationOverview {
  generated_at: string
  as_of: string
  window: SituationWindow
  source_snapshot: { algorithm: 'sha256'; data_version: string }
  summary: SituationSummary
  timeline: SituationTimelinePoint[]
  pattern_shifts: {
    case_types: PatternShift[]
    modus_operandi: PatternShift[]
    peak_hours: Array<{ hour: number; count: number }>
  }
  case_points: SituationCasePoint[]
  hotspots: SituationHotspot[]
  well_attention: WellAttention[]
  priorities: SituationPriority[]
  pipeline: Array<{
    step: string
    label: string
    status: 'completed' | 'degraded'
    result: string
  }>
  brief: {
    title: string
    headline: string
    facts: string[]
    findings: string[]
    suggestions: string[]
    markdown: string
  }
  boundary: {
    read_only: true
    historical_association_only: true
    statements: string[]
  }
}

export interface SituationQuery {
  windowDays?: number
  areaKeyword?: string
  hotspotRadiusKm?: number
  wellRadiusKm?: number
  minCases?: number
  asOf?: string
}

export const situationApi = {
  getOverview: async (query: SituationQuery = {}): Promise<SituationOverview> => {
    const response = await api.get<SituationOverview>('/situation/overview', {
      params: {
        window_days: query.windowDays ?? 30,
        area_keyword: query.areaKeyword?.trim() || undefined,
        hotspot_radius_km: query.hotspotRadiusKm ?? 1.5,
        well_radius_km: query.wellRadiusKm ?? 5,
        min_cases: query.minCases ?? 2,
        as_of: query.asOf,
      },
    })
    return response.data
  },
}
