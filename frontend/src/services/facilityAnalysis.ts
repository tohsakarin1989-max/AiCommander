import api from './api'
import type { AttentionItem } from '../types/attention'

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
  schema_version: 'facility-dossier-5.4-1' | 'facility-dossier-6.2-1'
  facility: Omit<RegionFacility, 'condition_comparison'>
  filters: { start_date?: string | null; end_date?: string | null }
  sections: Record<'production' | 'record_links' | 'nearby_cases' | 'candidate_links' | 'events' | 'results' | 'roads' | 'tech_defense' | 'history_conditions', FacilitySection>
  versions: Record<string, unknown>
  gaps: string[]
  boundary: string
  summary: { state: 'ready' | 'pending' | 'stale' | 'restricted'; revision: number | null; updated_at?: string | null; changes: unknown[] }
  identity?: FacilityIdentity
  temporal_context?: FacilityTemporalContext
  computability?: FacilityComputability
  attention_grounding?: AttentionItem & { version: string }
}
export interface FacilityIdentityItem {
  identity_id: number; source_id: number; source_name: string; source_record_id: string
  name: string; decision_id: number | null; status: string; identity_kind?: 'exact_id' | 'unidentified'
}
export interface FacilityIdentity {
  asset_id: number; state: string; items?: FacilityIdentityItem[]; boundary: string
}
export interface FacilityTemporalContext {
  valid_at: string | null; known_at: string | null; state: 'ready' | 'unknown' | 'conflict' | 'restricted' | 'partial'
  version_id?: number | null; valid_from?: string | null; valid_to?: string | null; recorded_at?: string | null
  snapshot?: { name?: string | null; asset_type?: string | null; attributes?: Record<string, unknown> } | null
  boundary: string
  knowledge_mode?: 'as_known' | 'retrospective'
  query_interval?: { from: string; to: string } | null
  coverage?: 'full' | 'partial' | 'unknown'
  late_supplement?: boolean
  groups?: Record<string, { state: string; coverage: 'full' | 'partial' | 'unknown'; gaps?: string[]; segments: Array<{
    from: string; to: string; end_inclusive: boolean; state: string; values: Record<string, unknown> | null;
    evidence_refs: string[]; known_at?: string | null; late_supplement?: boolean
  }> }>
}
export interface FacilityComputabilityCheck {
  key: string; label: string
  state: 'ready' | 'missing' | 'unverified' | 'disconnected' | 'restricted' | 'expired' | 'unavailable' | 'not_checked'
  detail: string; evidence_refs?: string[]
}
export interface FacilityComputability {
  state: 'ready' | 'partial' | 'missing'; checks: FacilityComputabilityCheck[]; boundary: string
}
export interface MapReadiness {
  items: Array<{ asset_id: number; name: string; asset_type: string; state: FacilityComputability['state']; checks: FacilityComputabilityCheck[] }>
  total: number; page: number; page_size: number; boundary: string
  context: { operational_area_id: number; [key: string]: unknown }
}
export interface FacilityDossierParams {
  start_date?: string; end_date?: string; valid_at?: string; known_at?: string
  valid_from?: string; valid_to?: string; knowledge_mode?: 'as_known' | 'retrospective'
}
export interface FacilityIdentityDecision { note: string; request_key: string; previous_decision_id: number | null }
export interface FacilityCaseLinkCreate {
  case_id: number; source_reference_id: number; source_revision_id: number
  relation_type: 'incident_site' | 'recovery_site' | 'mentioned'; note: string; request_key: string
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
  dossier: async (id: number, params: FacilityDossierParams, signal?: AbortSignal): Promise<FacilityDossier> =>
    (await api.get(`/facility-analysis/assets/${id}`, { params, signal })).data,
  readiness: async (params: { operational_area_id: number; page: number; page_size: number }, signal?: AbortSignal): Promise<MapReadiness> =>
    (await api.get('/facility-analysis/readiness', { params, signal })).data,
  bindIdentity: async (identityId: number, decision: FacilityIdentityDecision & { asset_id: number }): Promise<void> => {
    await api.post(`/facility-analysis/identities/${identityId}/bind`, decision)
  },
  revokeIdentity: async (identityId: number, decision: FacilityIdentityDecision): Promise<void> => {
    await api.post(`/facility-analysis/identities/${identityId}/revoke`, decision)
  },
  createCaseLink: async (assetId: number, data: FacilityCaseLinkCreate): Promise<void> => {
    await api.post(`/facility-analysis/assets/${assetId}/case-links`, data)
  },
  revokeCaseLink: async (associationId: number, note: string): Promise<void> => {
    await api.post(`/facility-analysis/case-links/${associationId}/revoke`, { note })
  },
  region: async (params: { operational_area_id: number; start_date?: string; end_date?: string; page?: number; page_size?: number }, signal?: AbortSignal): Promise<RegionalAnalysis> =>
    (await api.get('/facility-analysis/region', { params, signal })).data,
}
