import api from './api'

export interface HistoryReference {
  source_type: 'case' | 'experience_card' | 'legacy_experience_card'
  source_id: number; case_id: number; case_number: string; title: string; snippet: string; route: string
  shared_conditions: [string, string, string][]
  different_conditions: [string, string, string][]
  unmatched_query_conditions: [string, string, string][]
  score: number; score_kind: string; profile_state: string; derived_state?: string
  versions: Record<string, string | number | null>
  fragment?: { id: string; kind: string; source_revision_id: number | null; process_event_id?: string | null
    reference: { field: string; source_sha256: string; start: number; end: number; quote: string } }
  structural_rank?: number | null; lexical_rank?: number | null; semantic_rank?: number | null
}
export interface CaseHistoryResult {
  schema_version: 'case-history-5.1-1' | 'case-history-6.3-1'; source_case_id: number | null
  state: 'ready' | 'partial'; mode: string; semantic_index_state: string
  coverage: { authorized_cases: number; scanned_cases: number; matched_sources: number; complete: boolean
    scan_complete?: boolean; missing_derived_sources?: number
    indexed_cases?: number; missing_index_cases?: number; indexed_fragments?: number; recalled_fragments?: number
    validated_fragments?: number; invalidated_fragments?: number; recall_limit?: number; recall_truncated?: boolean
    branch_counts?: Record<string, number>; process_indexed_cases?: number; process_missing_cases?: number; process_index_state?: string }
  retrieval_mode?: 'fragment_index'; index_state?: 'pending' | 'partial' | 'ready'
  items: HistoryReference[]; boundary: string
}
export function isCaseHistoryResult(value: unknown): value is CaseHistoryResult {
  if (!value || typeof value !== 'object') return false
  const result = value as Partial<CaseHistoryResult>
  const coverage = result.coverage
  const conditionList = (items: unknown) => Array.isArray(items) && items.every(item =>
    Array.isArray(item) && item.length === 3 && item.every(part => typeof part === 'string'))
  const modern = result.schema_version === 'case-history-6.3-1'
  return ['case-history-5.1-1', 'case-history-6.3-1'].includes(result.schema_version || '') && ['ready', 'partial'].includes(result.state || '')
    && typeof result.mode === 'string' && typeof result.semantic_index_state === 'string'
    && typeof result.boundary === 'string' && !!coverage && typeof coverage.complete === 'boolean'
    && [coverage.authorized_cases, coverage.scanned_cases, coverage.matched_sources].every(n => Number.isInteger(n) && n >= 0)
    && (!modern || (result.retrieval_mode === 'fragment_index' && ['pending', 'partial', 'ready'].includes(result.index_state || '')
      && [coverage.indexed_cases, coverage.missing_index_cases, coverage.indexed_fragments, coverage.recalled_fragments,
        coverage.validated_fragments, coverage.invalidated_fragments, coverage.recall_limit].every(n => typeof n === 'number' && Number.isInteger(n) && n >= 0)))
    && Array.isArray(result.items) && result.items.every(item => item && typeof item === 'object'
      && ['case', 'experience_card', 'legacy_experience_card'].includes(item.source_type)
      && Number.isInteger(item.case_id) && item.case_id > 0
      && typeof item.title === 'string' && typeof item.snippet === 'string'
      && (!modern || (!!item.fragment && typeof item.fragment.id === 'string' && typeof item.fragment.kind === 'string'
        && !!item.fragment.reference && typeof item.fragment.reference.quote === 'string'
        && typeof item.fragment.reference.field === 'string' && /^[a-f0-9]{64}$/.test(item.fragment.reference.source_sha256)
        && Number.isInteger(item.fragment.reference.start) && item.fragment.reference.start >= 0
        && Number.isInteger(item.fragment.reference.end) && item.fragment.reference.end > item.fragment.reference.start
        && Array.from(item.fragment.reference.quote).length === item.fragment.reference.end - item.fragment.reference.start))
      && (item.route === `/cases?caseId=${item.case_id}` || item.route === `/case-intelligence?caseId=${item.case_id}`)
      && !!item.versions && typeof item.versions === 'object' && !Array.isArray(item.versions)
      && Object.values(item.versions).every(version => version == null || typeof version === 'string' || typeof version === 'number')
      && conditionList(item.shared_conditions) && conditionList(item.different_conditions)
      && conditionList(item.unmatched_query_conditions))
}
export const caseHistoryApi = {
  async read(caseId: number, signal?: AbortSignal): Promise<CaseHistoryResult> {
    const { data } = await api.get<CaseHistoryResult>('/knowledge/history', { params: { source_case_id: caseId, limit: 3 }, signal })
    if (!isCaseHistoryResult(data) || data.source_case_id !== caseId) throw new Error('历史参考来源不一致')
    return data
  },
}
