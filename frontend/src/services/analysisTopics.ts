import api from './api'
import type { QueryCaseFilters, QueryTask } from './intelligentQueries'
import type { CaseHistoryResult } from './caseHistory'

export type TopicCondition = { category: string; value?: string | null; kind: string }
export type TopicFilters = QueryCaseFilters & { conditions?: TopicCondition[] }
export interface Topic {
  id: string; title: string; notes: string; filters: TopicFilters; paused: boolean
  refresh_state: string; last_error: string | null; created_at: string; next_refresh_at: string | null
  snapshot?: TopicSnapshot | null
}
export interface TopicSnapshot {
  id: string; revision: number; content_sha256: string; created_at: string
  changes: Record<string, unknown>; aggregate: Record<string, unknown>
  events: { independent_event_count: number; case_linked_event_count: number; boundary?: string }
}
export interface TopicViews {
  snapshot_id: string; content_sha256: string; boundary: string
  map: { points: { case_id: number; latitude: number; longitude: number; operational_area_id: number | null }[]
    versions: { id: string; operational_area_id: number; version: string }[]; unmapped_in_page: number }
  graph: { groups: { category: string; value: string; kind: string; case_count: number; case_ids: number[] }[]
    case_ids: number[]; boundary: string }
  timeline: { case_id: number; occurred_time: string | null; profile_id: string; profile_version: number }[]
  case_results: { id: string; case_id: number; candidates: unknown[]; information_gaps: unknown[] }[]
  roads: { id: string; case_id: number; content: Record<string, unknown> }[]
  period_materials: { id: string; period_type: string; period_start: string; period_end: string
    summary: string; comparison_snapshot: Record<string, unknown>; information_gaps: unknown[] }[]
  history?: { state: string; boundary: string; result: CaseHistoryResult | null
    selection: { conditions: TopicCondition[]; available_condition_count: number; condition_limit: number; selection: string } } | null
}
export interface TopicEvidence {
  snapshot_id: string; content_sha256: string; boundary: string; information_gaps?: string[]
  assertions: { category: string; value: string; kind: string; evidence_ref: string
    reference: { quote: string; field: string; start: number; end: number } }[]
  model_extraction?: { state: string; boundary: string; version?: string; items: TopicEvidence['assertions'] }
}
const path = (id: string) => `/analysis-topics/${encodeURIComponent(id)}`
export const analysisTopicsApi = {
  list: async (page: number, signal?: AbortSignal): Promise<{ total: number; items: Topic[] }> =>
    (await api.get('/analysis-topics', { params: { page }, signal })).data,
  create: async (title: string, filters: TopicFilters): Promise<Topic> =>
    (await api.post('/analysis-topics', { title, filters })).data,
  fromQuery: async (queryId: string, title: string): Promise<Topic> =>
    (await api.post('/analysis-topics/from-query', { query_id: queryId, title })).data,
  read: async (id: string, revision: number | undefined, page: number, signal?: AbortSignal): Promise<Topic> =>
    (await api.get(path(id), { params: { revision, page }, signal })).data,
  views: async (id: string, revision: number, page: number, signal?: AbortSignal): Promise<TopicViews> =>
    (await api.get(`${path(id)}/views`, { params: { revision, page }, signal })).data,
  update: async (id: string, values: { notes?: string; paused?: boolean }): Promise<Topic> =>
    (await api.patch(path(id), values)).data,
  refresh: async (id: string): Promise<Topic> => (await api.post(`${path(id)}/refresh`)).data,
  history: async (id: string, page: number, signal?: AbortSignal): Promise<{ total: number; items: Pick<TopicSnapshot, 'revision' | 'created_at' | 'changes'>[] }> =>
    (await api.get(`${path(id)}/history`, { params: { page }, signal })).data,
  evidence: async (id: string, revision: number, caseId: number, signal?: AbortSignal): Promise<TopicEvidence> =>
    (await api.get(`${path(id)}/evidence/${caseId}`, { params: { revision }, signal })).data,
  question: async (id: string, revision: number, query: string): Promise<QueryTask> =>
    (await api.post(`${path(id)}/queries`, { revision, query })).data,
  document: async (id: string, revision: number, format: 'docx' | 'pdf', signal?: AbortSignal): Promise<Blob> =>
    (await api.get(`${path(id)}/document.${format}`, { params: { revision }, responseType: 'blob', signal })).data,
}
