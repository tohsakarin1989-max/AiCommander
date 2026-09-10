import api from './api'
import type { CaseResult, CaseResultCatalog } from '../types/caseResult'

export const caseResultsApi = {
  list: async (params: { q?: string; offset?: number; limit?: number } = {}): Promise<CaseResultCatalog> => {
    const response = await api.get<CaseResultCatalog>('/case-results', { params })
    return response.data
  },
  latest: async (caseId: number): Promise<CaseResult> => {
    const response = await api.get<CaseResult>(`/cases/${caseId}/results/latest`)
    return response.data
  },
  get: async (resultId: string): Promise<CaseResult> => {
    const response = await api.get<CaseResult>(`/case-results/${encodeURIComponent(resultId)}`)
    return response.data
  },
}
