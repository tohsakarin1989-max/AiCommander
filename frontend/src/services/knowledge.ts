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
}
