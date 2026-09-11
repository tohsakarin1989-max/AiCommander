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
  followup_context?: { parent_query_id: string; previous_question: string; previous_completed_at?: string | null;
    conditions: QueryConditions; parent_result_hash: string } | null
  result: { cards?: QueryCard[]; query_conditions?: QueryConditions;
    trace?: { step: number; tool: string; duration_ms?: number; error_code?: string;
      condition_changes?: { field: string; previous: unknown; current: unknown; basis: string }[] }[];
    error_code?: string | null }
}
export interface QueryConditions { case_filters: Record<string, unknown>; tool_defaults: Record<string, Record<string, unknown>>; area: number | null }
export const intelligentQueriesApi = {
  document: async (id: string, format: 'docx' | 'pdf', signal?: AbortSignal): Promise<Blob> =>
    (await api.get(`/intelligent-queries/${encodeURIComponent(id)}/document.${format}`, { responseType: 'blob', signal })).data,
  create: async (query: string, parentQueryId?: string): Promise<QueryTask> =>
    (await api.post('/intelligent-queries', { query, ...(parentQueryId ? { parent_query_id: parentQueryId } : {}) })).data,
  read: async (id: string, signal?: AbortSignal): Promise<QueryTask> =>
    (await api.get(`/intelligent-queries/${encodeURIComponent(id)}`, { signal })).data,
  cancel: async (id: string): Promise<{ id: string; status: string }> =>
    (await api.post(`/intelligent-queries/${encodeURIComponent(id)}/cancel`)).data,
}
