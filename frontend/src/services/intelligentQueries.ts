import api from './api'
import type { CasePageParams } from './cases'
import { parseCaseContextParams } from './caseContext'

export type QueryCaseFilters = Omit<CasePageParams, 'page' | 'page_size'>
export interface InitialQueryContext { source_case_id?: number; filters: QueryCaseFilters }
export interface QuerySourceCase { case_id: number; operational_area_id: number | null; source_hash: string }

/** Only page selection is submitted; source versions and permissions come from the server. */
export function queryEntryContext(params: URLSearchParams): { initialContext?: InitialQueryContext; error?: string } {
  const { caseId, filters, error } = parseCaseContextParams(params)
  if (error) return { error }
  const nonempty = Object.fromEntries(Object.entries(filters).filter(([, value]) =>
    value != null && (!Array.isArray(value) || value.length > 0) && (typeof value !== 'string' || value.trim())))
  if (caseId == null && Object.keys(nonempty).length === 0) return {}
  if (params.get('query')) return { error: '已有查询与新的案件选择不能混用，请先选择“新查询”。' }
  return { initialContext: { ...(caseId != null ? { source_case_id: caseId } : {}), filters: nonempty } }
}

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
  initial_context?: { schema_version: string; source_case: QuerySourceCase | null; conditions: QueryConditions } | null
  followup_context?: { parent_query_id: string; previous_question: string; previous_completed_at?: string | null;
    conditions: QueryConditions; parent_result_hash: string; source_case?: QuerySourceCase | null } | null
  result: { cards?: QueryCard[]; query_conditions?: QueryConditions;
    trace?: { step: number; tool: string; duration_ms?: number; error_code?: string;
      condition_changes?: { field: string; previous: unknown; current: unknown; basis: string }[] }[];
    error_code?: string | null }
}
export interface QueryConditions { case_filters: Record<string, unknown>; tool_defaults: Record<string, Record<string, unknown>>; area: number | null }
export const intelligentQueriesApi = {
  document: async (id: string, format: 'docx' | 'pdf', signal?: AbortSignal): Promise<Blob> =>
    (await api.get(`/intelligent-queries/${encodeURIComponent(id)}/document.${format}`, { responseType: 'blob', signal })).data,
  create: async (query: string, parentQueryId?: string, initialContext?: InitialQueryContext): Promise<QueryTask> => {
    if (parentQueryId && initialContext) throw new Error('已有查询与初始选择不能混用')
    return (await api.post('/intelligent-queries', { query,
      ...(parentQueryId ? { parent_query_id: parentQueryId } : {}),
      ...(initialContext ? { initial_context: initialContext } : {}),
    })).data
  },
  read: async (id: string, signal?: AbortSignal): Promise<QueryTask> =>
    (await api.get(`/intelligent-queries/${encodeURIComponent(id)}`, { signal })).data,
  cancel: async (id: string): Promise<{ id: string; status: string }> =>
    (await api.post(`/intelligent-queries/${encodeURIComponent(id)}/cancel`)).data,
}
