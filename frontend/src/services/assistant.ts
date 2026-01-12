import api from './api'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp?: string
}

export interface ChatRequest {
  query: string
  conversation_history?: ChatMessage[]
}

export interface ChatResponse {
  answer: string
  sources: Array<{
    type: 'case' | 'report'
    id?: number
    case_number?: string
    meeting_id?: string
  }>
  context_used?: {
    cases_count: number
    reports_count: number
  }
  error?: string
}

export interface StatsResponse {
  total_cases: number
  completed_meetings: number
  pending_meetings: number
}

export const assistantApi = {
  chat: async (request: ChatRequest): Promise<ChatResponse> => {
    const response = await api.post('/assistant/chat', request)
    return response.data
  },

  getStats: async (): Promise<StatsResponse> => {
    const response = await api.get('/assistant/stats')
    return response.data
  },
}

