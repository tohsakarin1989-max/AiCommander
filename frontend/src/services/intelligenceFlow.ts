import api from './api'

export type SemanticReference = {
  field: string; source_sha256: string; start: number; end: number; quote: string
}
export type CaseSemantics = {
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
  boundary?: string[]
}

export type CaseAnalysisProfileResult = {
  id: string
  case_id: number
  profile_version: number
  schema_version: string
  dictionary_version: string
  source_hash: string
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
    previous: { start: string; end: string; case_count: number; profile_versions_generated: number }
    current: { start: string; end: string; case_count: number; profile_versions_generated: number }
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
