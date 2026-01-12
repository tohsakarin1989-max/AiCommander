import api from './api'

export interface Conclusion {
  id: number
  case_id: number
  status: string
  confidence: number
  risk_level: string
  summary?: string
  evidence?: any
  review_reason?: string
  reviews?: Array<{
    id: number
    action: string
    note?: string
    created_at: string
  }>
  created_at: string
}

export interface ConclusionFilters {
  status?: string
  case_id?: number
  risk_level?: string
  min_confidence?: number
  max_confidence?: number
}

export const conclusionApi = {
  generate: async (caseId: number): Promise<Conclusion> => {
    const response = await api.post('/conclusions/generate', null, {
      params: { case_id: caseId },
    })
    return response.data
  },

  list: async (filters?: ConclusionFilters): Promise<Conclusion[]> => {
    const response = await api.get('/conclusions', { params: filters || {} })
    return response.data
  },

  get: async (id: number): Promise<Conclusion> => {
    const response = await api.get(`/conclusions/${id}`)
    return response.data
  },

  review: async (
    id: number,
    action: 'approve' | 'reject' | 'flag',
    note?: string,
  ): Promise<{ id: number; status: string; review_action: string }> => {
    const response = await api.post(`/conclusions/${id}/review`, null, {
      params: { action, note },
    })
    return response.data
  },
}
