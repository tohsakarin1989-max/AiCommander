import api from './api'
import type { CaseResult } from '../types/caseResult'

export const caseResultsApi = {
  latest: async (caseId: number): Promise<CaseResult> => {
    const response = await api.get<CaseResult>(`/cases/${caseId}/results/latest`)
    return response.data
  },
  get: async (resultId: string): Promise<CaseResult> => {
    const response = await api.get<CaseResult>(`/case-results/${encodeURIComponent(resultId)}`)
    return response.data
  },
}
