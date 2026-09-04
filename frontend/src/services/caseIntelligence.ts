import api from './api'
import type { Case, CaseQuality, TagCurationResult } from '../types'

export interface IntelligenceTag {
  key: string
  label: string
  category: string
  confidence: number
  basis: string[]
  manual?: boolean
  case_count?: number
}

export interface IntelligenceCounterItem {
  [key: string]: string | number | undefined
  count: number
}

export interface IntelligenceAsset {
  id: number | string
  name: string
  asset_type: string
  geometry_type?: string
  latitude?: number | null
  longitude?: number | null
  risk_level?: number | null
  verified?: boolean
  tags?: string[]
}

export interface CaseBrief {
  id: number
  case_number: string
  occurred_time?: string | null
  location?: string | null
  latitude?: number | null
  longitude?: number | null
  case_type?: string | null
  facility_type?: string | null
  oil_nature?: string | null
  source_type?: string | null
  quality_score?: number | null
}

export interface SimilarCaseItem {
  case: CaseBrief
  similarity_score: number
  components: Record<string, number>
  reasons: string[]
  duplicate_warnings: string[]
  shared_tags: string[]
}

export interface SimilarCasesPayload {
  case_id?: number | null
  case_number?: string
  principle: string
  items: SimilarCaseItem[]
}

export interface SpatiotemporalPayload {
  days: number
  case_count: number
  cases_with_geo: number
  hour_distribution: IntelligenceCounterItem[]
  period_distribution: IntelligenceCounterItem[]
  weekday_distribution: IntelligenceCounterItem[]
  month_distribution: IntelligenceCounterItem[]
  case_type_distribution: IntelligenceCounterItem[]
  facility_distribution: IntelligenceCounterItem[]
  source_distribution: IntelligenceCounterItem[]
  hotspots: Array<{
    center: { latitude: number; longitude: number }
    case_count: number
    case_ids: number[]
    case_numbers: string[]
  }>
  insights: string[]
}

export interface SceneAnalysisPayload {
  case_id?: number
  case_number?: string
  location_conditions?: IntelligenceTag[]
  vehicle_tool_patterns: {
    vehicles: IntelligenceCounterItem[]
    tools: IntelligenceCounterItem[]
    note?: string
  }
  site_weaknesses: IntelligenceCounterItem[]
  capture_experience: {
    source_type?: string | null
    distribution_in_similar_cases?: IntelligenceCounterItem[]
    lesson?: string
  } | IntelligenceCounterItem[]
  condition_frequency?: IntelligenceCounterItem[]
  reusable_rules?: string[]
  spatial_context?: Record<string, unknown>
}

export interface AreaProfile {
  asset: IntelligenceAsset
  risk_score: number
  risk_level: 'high' | 'medium' | 'low' | string
  case_count: number
  related_cases: Array<CaseBrief & { distance_km?: number }>
  common_tags: IntelligenceCounterItem[]
  top_hours: IntelligenceCounterItem[]
  risk_reasons: string[]
}

export interface AreaProfilesPayload {
  days: number
  radius_km: number
  profile_count: number
  items: AreaProfile[]
}

export interface PreventionSuggestion {
  id: string
  title: string
  priority: 'high' | 'medium' | 'low' | string
  action: string
  reason: string[]
  evidence: unknown[]
  confidence: number
  output_type: string
}

export interface PreventionSuggestionsPayload {
  case_id?: number | null
  suggestion_count: number
  items: PreventionSuggestion[]
  boundary: string
}

export interface ExperienceCardPayload {
  case_id: number
  case_number: string
  manual_review_status?: string
  reviewed_at?: string
  reviewer?: string
  summary: string
  what_happened: {
    time?: string | null
    location?: string | null
    case_type?: string | null
  }
  why_it_matters: string[]
  how_it_was_found: string[]
  reusable_lessons: string[]
  next_attention_points: string[]
  evidence_basis: Record<string, unknown>
}

export interface StructuredAiInference {
  claim: string
  basis: string[]
  confidence: string | number
}

export interface StructuredAiRecommendation {
  title: string
  action: string
  basis: string[]
  evidence: unknown[]
  confidence?: number | null
  priority?: string
}

export interface StructuredAiEvidenceRef {
  id: string
  kind: string
  summary: string
  basis?: string[]
}

export interface StructuredAiOutput {
  title: string
  output_type: string
  draft_status: 'draft' | string
  review_status: 'pending_review' | 'approved' | 'rejected' | string
  model_status: 'deterministic_fallback' | 'llm_success' | 'llm_failed' | string
  generated_at: string
  facts: string[]
  inferences: StructuredAiInference[]
  recommendations: StructuredAiRecommendation[]
  information_gaps: string[]
  evidence_refs: StructuredAiEvidenceRef[]
  boundary: string[]
  markdown: string
}

export interface IntelligenceReport {
  title: string
  generated_at: string
  case_id?: number | null
  days: number
  sections: Array<{ title: string; items: string[] }>
  markdown: string
  ai_output?: StructuredAiOutput
}

export interface LlmContextPack {
  scope: IntelligenceWorkbench['scope']
  selected_case?: CaseBrief | null
  system_boundary: string[]
  facts: string[]
  pattern_inferences: Array<{
    claim: string
    basis: string[]
    confidence: string
  }>
  inferences?: StructuredAiInference[]
  prevention_references: Array<{
    title?: string
    action?: string
    priority?: string
    basis?: string[]
    evidence?: unknown[]
    confidence?: number
  }>
  recommendations?: StructuredAiRecommendation[]
  information_gaps: string[]
  evidence_index: Array<{
    id: string
    kind: string
    summary: string
    basis?: string[]
  }>
  evidence_refs?: StructuredAiEvidenceRef[]
  boundary?: string[]
  recommended_questions: string[]
  llm_prompt: string
  markdown?: string
  ai_output?: StructuredAiOutput
  generated_at: string
}

export interface IntelligenceWorkbench {
  scope: {
    mode: 'single_case' | 'global'
    days: number
    limit: number
    radius_km: number
  }
  selected_case?: CaseBrief | null
  quality?: CaseQuality | null
  readiness?: Record<string, { status: string; blockers: string[] }> | null
  feature_tags: {
    case_id?: number | null
    case_number?: string
    tags: IntelligenceTag[]
    category_counts?: Record<string, number>
    context?: Record<string, unknown>
    principle?: string
  }
  similar_cases: SimilarCasesPayload
  spatiotemporal: SpatiotemporalPayload
  scene_analysis: SceneAnalysisPayload
  area_profiles: AreaProfilesPayload
  prevention_suggestions: PreventionSuggestionsPayload
  experience_card?: ExperienceCardPayload | null
  report: IntelligenceReport
}

export interface TagOverrideRequest {
  added?: Array<{
    key: string
    label?: string
    category?: string
    confidence?: number
    basis?: string[]
  }>
  removed_keys?: string[]
}

export const caseIntelligenceApi = {
  getWorkbench: async (params?: {
    case_id?: number
    days?: number
    limit?: number
    radius_km?: number
  }): Promise<IntelligenceWorkbench> => {
    const response = await api.get<IntelligenceWorkbench>('/case-intelligence/workbench', {
      params,
    })
    return response.data
  },

  getTags: async (caseId: number) => {
    const response = await api.get<IntelligenceWorkbench['feature_tags']>(`/case-intelligence/cases/${caseId}/tags`)
    return response.data
  },

  updateTagOverrides: async (caseId: number, data: TagOverrideRequest) => {
    const response = await api.put<IntelligenceWorkbench['feature_tags']>(
      `/case-intelligence/cases/${caseId}/tag-overrides`,
      data,
    )
    return response.data
  },

  curateTags: async (caseId: number, confirm = false): Promise<TagCurationResult> => {
    const response = await api.post<TagCurationResult>(
      `/case-intelligence/cases/${caseId}/tag-curation`,
      { confirm },
    )
    return response.data
  },

  getSimilarCases: async (caseId: number, params?: { days?: number; limit?: number }) => {
    const response = await api.get<SimilarCasesPayload>(`/case-intelligence/cases/${caseId}/similar`, { params })
    return response.data
  },

  getSpatiotemporal: async (days = 365) => {
    const response = await api.get<SpatiotemporalPayload>('/case-intelligence/spatiotemporal', {
      params: { days },
    })
    return response.data
  },

  getAreaProfiles: async (params?: { days?: number; limit?: number; radius_km?: number }) => {
    const response = await api.get<AreaProfilesPayload>('/case-intelligence/area-profiles', { params })
    return response.data
  },

  getSuggestions: async (params?: { case_id?: number; days?: number; limit?: number }) => {
    const response = await api.get<PreventionSuggestionsPayload>('/case-intelligence/prevention-suggestions', { params })
    return response.data
  },

  getExperienceCard: async (caseId: number) => {
    const response = await api.get<ExperienceCardPayload>(`/case-intelligence/cases/${caseId}/experience-card`)
    return response.data
  },

  getReport: async (params?: { case_id?: number; days?: number; limit?: number }) => {
    const response = await api.get<IntelligenceReport>('/case-intelligence/report', { params })
    return response.data
  },

  getLlmContext: async (params?: {
    case_id?: number
    days?: number
    limit?: number
    radius_km?: number
  }) => {
    const response = await api.get<LlmContextPack>('/case-intelligence/llm-context', { params })
    return response.data
  },
}

export type { Case }
