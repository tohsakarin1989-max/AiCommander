import api from './api'
import type { CasePageParams } from './cases'
import { parseCaseContextParams } from './caseContext'

export type QueryCaseFilters = Omit<CasePageParams, 'page' | 'page_size'>
export interface InitialQueryContext { source_case_id?: number; filters: QueryCaseFilters }
export interface QuerySourceCase { case_id: number; operational_area_id: number | null; source_hash: string }
export type QueryPresetName = 'case_count' | 'case_process' | 'case_result' | 'facility_dossier' | 'facility_history' | 'coverage_scenario'
export interface QueryPreset { name: QueryPresetName; arguments: Record<string, unknown> }
export type BusinessQuestionType = 'case_history' | 'attention' | 'recent_changes'
export interface BusinessSourceContext {
  case_id?: number; asset_id?: number; area_id?: number
  time_basis?: 'discovery' | 'incident' | 'entry'; period?: 'daily' | 'weekly'; as_of?: string
}
export interface BusinessEvidence { text: string; evidence_refs: string[] }
export interface BusinessAnswerMapContext {
  schema_version: 'business-answer-map-8.4-1'; state: 'ready' | 'partial' | 'unavailable'
  snapshots: Array<{ id: string; version: string; area_id: number }>
  points: Array<{ kind: 'case' | 'asset'; object_id: number; label: string; role: string;
    latitude: number; longitude: number; map_snapshot_id: string; evidence_refs: string[] }>
  coverage: { point_limit: number; shown: number; truncated: boolean }
  information_gaps: string[]; boundary: string
}
export interface EvidenceAnswer {
  schema_version: 'query-answer-6.4-1' | 'business-answer-8.4-1'; summary: string
  findings: Array<{ text: string; card_index: number; evidence_refs: string[] }>
  information_gaps: string[]; boundary: string
  direct_answer?: string
  map_context?: BusinessAnswerMapContext
  completeness?: 'answered' | 'partial' | 'insufficient_data' | 'service_unavailable'
  evidence?: BusinessEvidence[]; differences?: BusinessEvidence[]; unanswered?: string[]
  time_scope_versions?: {
    source_context: BusinessSourceContext; algorithm_version: string; scope_version: string; answered_at: string
    selection?: 'explicit_area_history' | 'all_authorized_history' | 'authorized_area_equal_periods'
    history_area_filter?: number | null
    source_versions: Array<{ kind: string; id: string | number; version: string | number | null }>
  }
}

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
  continuation?: AggregateContinuation | { status: 'unavailable'; error_code?: string }
}
export interface AggregateContinuation {
  id: string
  status: 'pending' | 'retry' | 'processing' | 'completed' | 'cancelled' | 'superseded' | 'failed'
  progress: { phase: string; scanned_cases: number; total_cases: number | null }
  as_of: string
  scope_version: string
  error?: string | null
  result?: Record<string, unknown> | null
}
export interface QueryTask {
  id: string
  query: string
  status: string
  result_kind: string
  question_type?: BusinessQuestionType | null
  source_context?: BusinessSourceContext | null
  clarification?: { id: string; field: 'case_id' | 'area_id'; prompt: string; expires_at: string } | null
  initial_context?: { schema_version: string; source_case: QuerySourceCase | null; conditions: QueryConditions } | null
  followup_context?: { parent_query_id: string; previous_question: string; previous_completed_at?: string | null;
    conditions: QueryConditions; parent_result_hash: string; source_case?: QuerySourceCase | null } | null
  result: { cards?: QueryCard[]; query_conditions?: QueryConditions;
    execution_mode?: 'deterministic_preset' | 'intranet_model' | 'deterministic_business_question'; answer?: EvidenceAnswer
    usage?: { model_requests: number; input_tokens: number | null; output_tokens: number | null; token_state: string; tool_calls: number; duration_ms: number }
    trace?: { step: number; tool: string; duration_ms?: number; error_code?: string;
      condition_changes?: { field: string; previous: unknown; current: unknown; basis: string }[] }[];
    error_code?: string | null }
}
export interface QueryConditions { case_filters: Record<string, unknown>; tool_defaults: Record<string, Record<string, unknown>>; area: number | null }
export const intelligentQueriesApi = {
  askBusiness: async (query: string, questionType: BusinessQuestionType, sourceContext: BusinessSourceContext, parentQueryId?: string): Promise<QueryTask> =>
    (await api.post('/intelligent-queries', { query, question_type: questionType, source_context: sourceContext,
      ...(parentQueryId ? { parent_query_id: parentQueryId } : {}) })).data,
  clarify: async (id: string, payload: { clarification_id: string; request_id: string; value: number }): Promise<QueryTask> =>
    (await api.post(`/intelligent-queries/${encodeURIComponent(id)}/clarifications`, payload)).data,
  document: async (id: string, format: 'docx' | 'pdf', signal?: AbortSignal): Promise<Blob> =>
    (await api.get(`/intelligent-queries/${encodeURIComponent(id)}/document.${format}`, { responseType: 'blob', signal })).data,
  create: async (query: string, parentQueryId?: string, initialContext?: InitialQueryContext, preset?: QueryPreset): Promise<QueryTask> => {
    if (parentQueryId && initialContext) throw new Error('已有查询与初始选择不能混用')
    return (await api.post('/intelligent-queries', { query,
      ...(parentQueryId ? { parent_query_id: parentQueryId } : {}),
      ...(initialContext ? { initial_context: initialContext } : {}),
      ...(preset ? { preset } : {}),
    })).data
  },
  read: async (id: string, signal?: AbortSignal): Promise<QueryTask> =>
    (await api.get(`/intelligent-queries/${encodeURIComponent(id)}`, { signal })).data,
  cancel: async (id: string): Promise<{ id: string; status: string }> =>
    (await api.post(`/intelligent-queries/${encodeURIComponent(id)}/cancel`)).data,
  readContinuation: async (id: string, signal?: AbortSignal): Promise<AggregateContinuation> =>
    (await api.get(`/analysis-topics/aggregations/${encodeURIComponent(id)}`, { signal })).data,
  cancelContinuation: async (id: string): Promise<AggregateContinuation> =>
    (await api.post(`/analysis-topics/aggregations/${encodeURIComponent(id)}/cancel`)).data,
}
