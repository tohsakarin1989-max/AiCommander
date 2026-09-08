import api from './api'
import type {
  EvidenceQaResponse,
  KnowledgeSearchResponse,
  ReportReviewResult,
} from '../types'

export interface ExperienceKnowledgeResponse {
  items: Array<{
    source_type: string
    source_id: number
    case_id: number
    case_number: string
    title: string
    summary: string
    snippet: string
    score: number
    manual_review_status: string
    applicability_reason: string
    evidence_refs: Array<Record<string, unknown>>
    route: string
  }>
  total: number
  query?: string
  status?: string
  generated_at: string
}

export interface CitationAssistResponse {
  query: string
  citations: Array<{
    title: string
    snippet: string
    source_type: string
    source_id: number | string
    route: string
    evidence_refs: Array<Record<string, unknown>>
  }>
  draft_lines: string[]
  insufficient_evidence: boolean
  boundary: string
}

export type KnowledgeAssetStatus = 'draft' | 'confirmed' | 'archived'

export interface KnowledgeAssetRecord {
  id: number
  asset_type: 'experience_card' | 'case_report'
  source_case_id: number
  source_case_number?: string | null
  version: number
  title: string
  content: Record<string, any>
  evidence_refs: Array<Record<string, any>>
  source_signature: string
  source_data_version: string
  status: KnowledgeAssetStatus
  reviewer_label?: string | null
  review_note?: string | null
  reviewed_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface KnowledgeAssetListResponse {
  items: KnowledgeAssetRecord[]
  total: number
}

export interface ExperienceReuseRecommendation {
  asset_id: number
  version: number
  status: KnowledgeAssetStatus
  source_case_id: number
  source_case_number: string
  title: string
  summary: string
  similarity_score: number
  applicability_reasons: string[]
  mismatch_risks: string[]
  shared_tags: string[]
  evidence_refs: Array<Record<string, any>>
  latest_decision?: 'accepted' | 'rejected' | 'referenced' | null
  already_reused: boolean
}

export interface ExperienceReuseRecommendationsResponse {
  target_case_id: number
  target_case_number: string
  items: ExperienceReuseRecommendation[]
  manual_selection_required: boolean
  boundary: string
}

export interface KnowledgeReuseRecord {
  id: number
  source_asset_id: number
  source_case_id?: number | null
  source_case_number?: string | null
  target_case_id: number
  target_asset_id?: number | null
  decision: 'accepted' | 'rejected' | 'referenced'
  purpose: string
  applicability: Record<string, unknown>
  note?: string | null
  created_at?: string | null
}

export interface KnowledgeReuseRecordResponse {
  target_case_id: number
  items: KnowledgeReuseRecord[]
  total: number
}

export const knowledgeApi = {
  search: async (params: { q: string; case_id?: number; limit?: number }): Promise<KnowledgeSearchResponse> => {
    const response = await api.get<KnowledgeSearchResponse>('/knowledge/search', { params })
    return response.data
  },

  listExperienceCards: async (params?: { status?: string; limit?: number }): Promise<ExperienceKnowledgeResponse> => {
    const response = await api.get<ExperienceKnowledgeResponse>('/knowledge/experience-cards', { params })
    return response.data
  },

  searchExperienceCards: async (params: { q: string; status?: string; limit?: number }): Promise<ExperienceKnowledgeResponse> => {
    const response = await api.get<ExperienceKnowledgeResponse>('/knowledge/experience-cards/search', { params })
    return response.data
  },

  updateExperienceCardStatus: async (
    caseId: number,
    payload: { status: 'draft' | 'confirmed' | 'archived'; reviewer?: string; note?: string },
  ): Promise<Record<string, unknown>> => {
    const response = await api.post<Record<string, unknown>>(`/knowledge/experience-cards/${caseId}/status`, payload)
    return response.data
  },

  evidenceQa: async (payload: { query: string; case_id?: number }): Promise<EvidenceQaResponse> => {
    const response = await api.post<EvidenceQaResponse>('/assistant/evidence-qa', payload)
    return response.data
  },

  citationAssist: async (payload: { query: string; case_id?: number }): Promise<CitationAssistResponse> => {
    const response = await api.post<CitationAssistResponse>('/reports/citation-assist', payload)
    return response.data
  },

  reviewReport: async (reportId: number): Promise<ReportReviewResult> => {
    const response = await api.post<ReportReviewResult>(`/reports/${reportId}/review`)
    return response.data
  },

  listAssets: async (params?: {
    asset_type?: 'experience_card' | 'case_report'
    case_id?: number
    status?: KnowledgeAssetStatus
    limit?: number
  }): Promise<KnowledgeAssetListResponse> => {
    const response = await api.get<KnowledgeAssetListResponse>('/knowledge/assets', { params })
    return response.data
  },

  generateExperienceAsset: async (caseId: number): Promise<KnowledgeAssetRecord> => {
    const response = await api.post<KnowledgeAssetRecord>(`/knowledge/cases/${caseId}/experience-assets`)
    return response.data
  },

  generateReportSnapshot: async (
    caseId: number,
    payload: { experience_asset_ids: number[]; days?: number; limit?: number },
  ): Promise<KnowledgeAssetRecord> => {
    const response = await api.post<KnowledgeAssetRecord>(`/knowledge/cases/${caseId}/report-snapshots`, payload)
    return response.data
  },

  reviewAsset: async (
    assetId: number,
    payload: { status: 'confirmed' | 'archived'; note?: string },
  ): Promise<KnowledgeAssetRecord> => {
    const response = await api.post<KnowledgeAssetRecord>(`/knowledge/assets/${assetId}/review`, payload)
    return response.data
  },

  getReuseRecommendations: async (
    caseId: number,
    params?: { days?: number; limit?: number },
  ): Promise<ExperienceReuseRecommendationsResponse> => {
    const response = await api.get<ExperienceReuseRecommendationsResponse>(
      `/knowledge/cases/${caseId}/reuse-recommendations`,
      { params },
    )
    return response.data
  },

  recordReuseDecision: async (payload: {
    source_asset_id: number
    target_case_id: number
    decision: 'accepted' | 'rejected'
    purpose: string
    note?: string
  }): Promise<KnowledgeReuseRecord> => {
    const response = await api.post<KnowledgeReuseRecord>('/knowledge/reuse-decisions', payload)
    return response.data
  },

  listReuseRecords: async (
    targetCaseId: number,
    limit = 100,
  ): Promise<KnowledgeReuseRecordResponse> => {
    const response = await api.get<KnowledgeReuseRecordResponse>('/knowledge/reuse-records', {
      params: { target_case_id: targetCaseId, limit },
    })
    return response.data
  },
}
