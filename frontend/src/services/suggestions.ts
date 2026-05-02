import api from './api'

export type SuggestionPriority = 'high' | 'medium' | 'low'

export interface WorkSuggestion {
  id: string
  type: string
  priority: SuggestionPriority
  title: string
  description: string
  target_type: 'case' | 'event' | 'conclusion' | 'meeting' | 'area' | string
  target_id: number | string
  action: string
  status: string
  created_at: string
}

export interface SuggestionsResponse {
  suggestions: WorkSuggestion[]
  total: number
  generated_at: string
}

export const suggestionsApi = {
  list: async (params?: { limit?: number; status?: string }): Promise<SuggestionsResponse> => {
    const response = await api.get<SuggestionsResponse>('/suggestions/', { params })
    return response.data
  },
}
