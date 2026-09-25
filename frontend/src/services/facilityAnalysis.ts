import api from './api'

export type EvidenceState = 'ready' | 'empty' | 'missing' | 'stale' | 'restricted' | 'unavailable' | 'partial'
export interface FacilityEvidence {
  id: string | number
  label: string
  detail?: string
  case_id?: number
  event_id?: number
  evidence_refs?: string[]
  support?: string[]
  counter?: string[]
  gaps?: string[]
  [key: string]: unknown
}
export interface FacilitySection {
  state: EvidenceState
  items?: FacilityEvidence[]
  total?: number
  gaps?: string[]
  boundary?: string
}
export interface FacilityReference {
  case_id: number
  title: string
  similar: string[]
  different: string[]
  gaps: string[]
  evidence_refs: string[]
  historical_conditions?: string[]
}
export interface RegionFacility {
  id: number
  name: string
  asset_type: string
  operational_area_id: number
  external_id?: string | null
  latitude?: number | null
  longitude?: number | null
  verified?: boolean
  condition_comparison: { state: EvidenceState; reference_cases?: FacilityReference[]; gaps: string[]; boundary: string }
  [key: string]: unknown
}
export interface FacilityDossier {
  schema_version: 'facility-dossier-5.4-1'
  facility: Omit<RegionFacility, 'condition_comparison'>
  filters: { start_date?: string | null; end_date?: string | null }
  sections: Record<'production' | 'record_links' | 'nearby_cases' | 'candidate_links' | 'events' | 'results' | 'roads' | 'tech_defense' | 'history_conditions', FacilitySection>
  versions: Record<string, unknown>
  gaps: string[]
  boundary: string
  summary: { state: 'ready' | 'pending' | 'stale' | 'restricted'; revision: number | null; updated_at?: string | null; changes: unknown[] }
}
export interface RegionalCase {
  id: number; case_number: string; occurred_time?: string | null; latitude?: number | null; longitude?: number | null
  case_type?: string | null; operational_area_id?: number | null
}
export interface RegionalEvent {
  id: number; event_number: string; title?: string | null; occurred_time?: string | null; related_case_id?: number | null
  latitude?: number | null; longitude?: number | null; event_type?: string
  case_in_window?: boolean | null; review_status?: string
}
export interface RegionalAnalysis {
  scope: { operational_area_id: number; area_name: string; authorized_area_ids?: number[] }
  window: { start_date?: string | null; end_date?: string | null }
  facilities: { items: RegionFacility[]; total: number; page: number; page_size: number }
  cases: { items: RegionalCase[]; total: number; missing_coordinates: number }
  events: { items: RegionalEvent[]; total: number; linked_case_count: number; independent_count: number; linked_case_outside_window_count?: number }
  statistics: { hour_day?: { weekday: number; hour: number; count: number }[]; monthly?: { month: string; case_count: number; event_count: number }[];
    spatial_monthly?: { month: string; cell_latitude: number; cell_longitude: number; case_count: number }[]; spatial_grid_degrees?: number; [key: string]: unknown }
  versions: { map_snapshot_id?: string | null; [key: string]: unknown }
  coverage: { state: string; cases_truncated: boolean; events_truncated: boolean; [key: string]: unknown }
  boundary: string
}

export const facilityAnalysisApi = {
  dossier: async (id: number, params: { start_date?: string; end_date?: string }, signal?: AbortSignal): Promise<FacilityDossier> =>
    (await api.get(`/facility-analysis/assets/${id}`, { params, signal })).data,
  region: async (params: { operational_area_id: number; start_date?: string; end_date?: string; page?: number; page_size?: number }, signal?: AbortSignal): Promise<RegionalAnalysis> =>
    (await api.get('/facility-analysis/region', { params, signal })).data,
}
