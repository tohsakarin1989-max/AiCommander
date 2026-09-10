import api from './api'

export interface QueryCard {
  tool: string
  state: string
  data: Record<string, unknown>
  information_gaps?: string[]
  evidence?: { source?: string; queried_at?: string; filters?: Record<string, unknown>; tool_version?: string }
  boundary?: string
}
export interface QueryTask {
  id: string
  query: string
  status: string
  result_kind: string
  result: { cards?: QueryCard[]; trace?: { step: number; tool: string; duration_ms?: number }[]; error_code?: string | null }
}
export const intelligentQueriesApi = {
  create: async (query: string): Promise<QueryTask> => (await api.post('/intelligent-queries', { query })).data,
  read: async (id: string, signal?: AbortSignal): Promise<QueryTask> =>
    (await api.get(`/intelligent-queries/${encodeURIComponent(id)}`, { signal })).data,
  cancel: async (id: string): Promise<{ id: string; status: string }> =>
    (await api.post(`/intelligent-queries/${encodeURIComponent(id)}/cancel`)).data,
}
