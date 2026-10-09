import api from './api'
import type { AttentionGrounding } from '../types/attention'
import type { CaseProcess } from './caseProcess'

export type SemanticReference = {
  field: string; source_sha256: string; start: number; end: number; quote: string
}
export type CaseSemantics = {
  process?: CaseProcess
  field_observations?: {
    schema_version: string
    items: Array<{
      id: string; category: string; label: string; kind: string; reference: SemanticReference
      measurements: Array<{ value: number; unit: string; oil_type: string; stage: string; kind: string; reference: SemanticReference; is_official_fact: false }>
      is_official_fact: false
    }>
    coverage: { state: string; limit: number; omitted_items: number }
    boundary: string
  }
  rule_version: string
  method: string
  assertions: Array<{
    category: string; value: string; kind: string; reference: SemanticReference
    is_official_fact: false
  }>
  time_intervals?: Array<{
    start: string; end: string; start_precision: string; end_precision: string
    reference: SemanticReference; timezone: string | null
  }>
  structured_sources?: {
    entries: Array<{ reference: { field: string; path: Array<string | number>; value: unknown } }>
  }
  potential_conflicts?: Array<{ category: string; value: string; status: string }>
  information_gaps?: Array<{ code: string; field?: string; reference?: SemanticReference }>
  model_extraction?: {
    status: string; version: string; adapter_version: string; model_id: number | null
    items: Array<{ category: string; value: string; kind: string; reference: SemanticReference; is_official_fact: false }>
    rejected_items: number; boundary: string
  }
  event_fragments?: {
    schema_version: string
    items: Array<{
      id: string; reference: SemanticReference
      actions: Array<{ value: string; kind: string; reference: SemanticReference; is_official_fact: false }>
      assertion_indices: number[]; time_interval_indices: number[]; missing_dimensions: string[]
      relation_status: string; is_official_fact: false
    }>
    coverage: { state: string; limit: number; omitted_fragments: number; input_assertions_partial?: boolean }
    deep_model_status: string
    boundary: string
  }
  boundary?: string[]
}

export type CaseAnalysisProfileResult = {
  id: string
  case_id: number
  profile_version: number
  schema_version: string
  dictionary_version: string
  source_hash: string
  source_revision_id?: number | null
  freshness?: 'current' | 'updating'
  is_current?: boolean
  freshness_boundary?: string
  quality_score: number
  analysis_readiness: string
  payload: {
    semantics?: CaseSemantics
    critical_gaps?: Array<{ field: string; label: string; reason: string }>
    spatial_grid?: string | null
    boundary?: string
  }
  created_at: string
}

export type CaseHypothesisResult = {
  id: string
  rank: number
  hypothesis_type: string
  title: string
  claim: string
  score: number
  confidence: number
  region?: Record<string, unknown> | null
  evidence_refs: string[]
  supporting_evidence: string[]
  counter_evidence: string[]
  information_gaps: string[]
  boundary: string
}

export type CaseInsightResult = {
  id: string
  case_id: number
  status: string
  case_profile_id: string
  summary?: string | null
  algorithm_version: string
  map_snapshot_id: string
  information_gaps: string[]
  hypotheses: CaseHypothesisResult[]
  completed_at?: string | null
}

export type CasePipelineStatusResult = {
  case_id: number
  status: string
  source_hash?: string | null
  event_id?: string | null
  attempts?: number
  last_error?: string | null
}

export type DeploymentRecommendationResult = {
  id: string
  rank: number
  title: string
  target_area: string
  time_window: string
  suggested_action: string
  resource_assumption: string
  expected_effect: string
  evidence_refs: string[]
  supporting_evidence: string[]
  information_gaps: string[]
  confidence: number | null
  confidence_kind?: string
  valid_until: string
  boundary: string
}

export type SituationBriefResult = {
  id: string
  period_type: 'daily' | 'weekly'
  period_start: string
  period_end: string
  status: string
  summary: string
  algorithm_version: string
  scope_policy_version: string
  evidence_refs: string[]
  information_gaps: string[]
  generated_at: string
  recommendations: DeploymentRecommendationResult[]
  comparison_snapshot?: {
    timezone: string
    attention?: AttentionGrounding
    time_basis?: 'discovery' | 'incident' | 'entry'
    time_basis_label?: string
    boundary?: string
    quality?: {
      denominator: number; denominator_label: string; unknown_time_count: number; unknown_time_ratio: number | null
      unclear_place_count: number; unclear_place_ratio: number | null
      unstructured_method_count: number; unstructured_method_ratio: number | null; boundary: string
    }
    change_origins?: {
      recent_registered: { case_ids: number[]; count: number; label: string }
      late_entry: { case_ids: number[]; count: number; label: string }
      entry_time_uncertain: { case_ids: number[]; count: number; label: string }
      corrections: { items: { case_id: number; revision_id: number; change_id: number; change_type: string }[]; count: number; label: string }
      withdrawals: { audit_ids: number[]; count: number; label: string }
      boundary: string
    }
    snapshot_change?: {
      state: 'comparable' | 'incomparable'; reason?: string; material_changed?: boolean; boundary?: string
      items: { kind: string; case_ids: number[]; label: string }[]
    }
    previous: { start: string; end: string; case_count: number; profile_versions_generated: number; uncertain_count?: number }
    current: { start: string; end: string; case_count: number; profile_versions_generated: number; uncertain_count?: number }
    semantic_changes?: {
      state: string; boundary: string; information_gaps: string[]
      previous: { case_count: number; readable_case_count: number }
      current: { case_count: number; readable_case_count: number }
      changes: { category: string; value: string; kind: string; previous_count: number; current_count: number; case_count_change: number }[]
    }
    roads?: {
      state: string; boundary: string; information_gaps: string[]
      items: { source_id: number; feature_id: string; name: string; kind: string; change: string;
        changed_fields: string[]; before_import_id: number | null; after_import_id: number;
        previous_conditions: Record<string, string | number> | null; current_conditions: Record<string, string | number>;
        previous_status?: { validity: string; review_state: string } | null;
        current_status?: { validity: string; review_state: string };
        evidence_refs: string[] }[]
    }
    tech_defense?: { boundary: string; information_gaps: string[]; items: {
      source_id: number; device_type: string; state: string; information_gaps: string[];
      previous?: { reported_offline: number }; current?: { reported_offline: number };
      offline_change?: number; alert_change?: number;
    }[] }
  } | null
}

export const intelligenceFlowApi = {
  getCasePipelineStatus: async (caseId: number): Promise<CasePipelineStatusResult> => {
    const response = await api.get<CasePipelineStatusResult>(`/cases/${caseId}/pipeline-status`)
    return response.data
  },

  getCaseAnalysisProfile: async (caseId: number): Promise<CaseAnalysisProfileResult> => {
    const response = await api.get<CaseAnalysisProfileResult>(`/cases/${caseId}/analysis-profile/latest`)
    return response.data
  },

  getCaseInsights: async (caseId: number): Promise<CaseInsightResult> => {
    const response = await api.get<CaseInsightResult>(`/cases/${caseId}/insights/latest`)
    return response.data
  },

  getLatestSituationBrief: async (): Promise<SituationBriefResult> => {
    const response = await api.get<SituationBriefResult>('/situation/briefs/latest')
    return response.data
  },

  submitRecommendationFeedback: async (
    recommendationId: string,
    decision: 'adopt_reference' | 'not_adopted' | 'insufficient_information',
    usefulnessScore?: number,
  ): Promise<{ execution_task_created: boolean }> => {
    const response = await api.post(`/deployment-recommendations/${recommendationId}/feedback`, {
      decision,
      usefulness_score: usefulnessScore,
    })
    return response.data
  },
}
