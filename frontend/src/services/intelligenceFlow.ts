import api from './api'

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
  confidence: number
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
