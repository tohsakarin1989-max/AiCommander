import api from './api'

export interface ProcessTextReference {
  field: string; source_sha256: string; start: number; end: number; quote: string; source_revision_id: number
}
export interface HistoryProcessSide {
  event_id: string; statement_kind: string; action_kind: string
  reference: ProcessTextReference; action_reference: ProcessTextReference
}
export interface HistoryProcessComparison {
  version: 'history-process-comparison-7.5-1'
  state: 'ready' | 'partial' | 'unavailable'; reason: string; boundary: string
  current: { case_id: number; profile_id: string | null; source_revision_id: number | null; source_hash: string | null }
  historical: HistoryProcessComparison['current']
  pairs: Array<{ action: string; relation: 'stated_match' | 'negated_match' | 'uncertain' | 'counter'
    current: HistoryProcessSide; historical: HistoryProcessSide
    shared_conditions: [string, string, string][]; current_only_conditions: [string, string, string][]
    historical_only_conditions: [string, string, string][]; counter_conditions: [string, string, string][]
    current_missing_dimensions: string[]; historical_missing_dimensions: string[] }>
  unmatched_current: Array<{ event_id: string; actions: Array<{ value: string; kind: string }>; reference: ProcessTextReference }>
  unmatched_historical: HistoryProcessComparison['unmatched_current']
  coverage: { complete: boolean; pair_limit: number; omitted_pairs: number }
}

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
  process_comparison?: HistoryProcessComparison
}
function validProcessComparison(value: HistoryProcessComparison | undefined, sourceId: number | null, historyId: number): boolean {
  if (value === undefined) return true // Historical materials retain their original contract.
  if (!value || value.version !== 'history-process-comparison-7.5-1' || !['ready', 'partial', 'unavailable'].includes(value.state)
      || typeof value.reason !== 'string' || typeof value.boundary !== 'string') return false
  const source = (s: HistoryProcessComparison['current'], id: number | null) => s && id !== null && s.case_id === id
    && (s.profile_id === null || typeof s.profile_id === 'string')
    && (s.source_revision_id === null ? s.source_hash === null : Number.isInteger(s.source_revision_id) && s.source_revision_id > 0 && /^[a-f0-9]{64}$/.test(s.source_hash || ''))
  if (!source(value.current, sourceId) || !source(value.historical, historyId)) return false
  const strings = (items: unknown) => Array.isArray(items) && items.every(item => typeof item === 'string')
  const tuples = (items: unknown) => Array.isArray(items) && items.every(item => Array.isArray(item) && item.length === 3 && strings(item))
  const ref = (r: ProcessTextReference, revision: number | null) => r && typeof r.field === 'string' && /^[a-f0-9]{64}$/.test(r.source_sha256)
    && revision !== null && r.source_revision_id === revision && Number.isInteger(r.start) && r.start >= 0
    && Number.isInteger(r.end) && r.end > r.start && typeof r.quote === 'string' && Array.from(r.quote).length === r.end - r.start
  const side = (s: HistoryProcessComparison['pairs'][number]['current'], revision: number | null) => s && typeof s.event_id === 'string'
    && ['stated', 'negated', 'uncertain', 'inferred', 'mixed'].includes(s.statement_kind)
    && ['stated', 'negated', 'uncertain', 'inferred'].includes(s.action_kind) && ref(s.reference, revision) && ref(s.action_reference, revision)
    && s.action_reference.field === s.reference.field && s.action_reference.source_sha256 === s.reference.source_sha256
    && s.action_reference.start >= s.reference.start && s.action_reference.end <= s.reference.end
  const unmatched = (items: HistoryProcessComparison['unmatched_current'], revision: number | null) => Array.isArray(items) && items.every(item =>
    typeof item.event_id === 'string' && ref(item.reference, revision) && Array.isArray(item.actions)
    && item.actions.every(action => typeof action.value === 'string' && ['stated', 'negated', 'uncertain', 'inferred'].includes(action.kind)))
  return !!value.coverage && typeof value.coverage.complete === 'boolean' && value.coverage.pair_limit === 24
    && Number.isInteger(value.coverage.omitted_pairs) && value.coverage.omitted_pairs >= 0
    && Array.isArray(value.pairs) && value.pairs.length <= 24 && value.pairs.every(pair => {
      if (!side(pair.current, value.current.source_revision_id) || !side(pair.historical, value.historical.source_revision_id)) return false
      const a = pair.current.action_kind, b = pair.historical.action_kind
      const relation = a === 'stated' && b === 'stated' ? 'stated_match' : a === 'negated' && b === 'negated' ? 'negated_match'
        : [a, b].includes('stated') && [a, b].includes('negated') ? 'counter' : 'uncertain'
      return typeof pair.action === 'string' && pair.relation === relation
        && [pair.shared_conditions, pair.current_only_conditions, pair.historical_only_conditions, pair.counter_conditions].every(tuples)
        && strings(pair.current_missing_dimensions) && strings(pair.historical_missing_dimensions)
    }) && unmatched(value.unmatched_current, value.current.source_revision_id) && unmatched(value.unmatched_historical, value.historical.source_revision_id)
    && (value.state !== 'unavailable' || (value.pairs.length === 0 && value.unmatched_current.length === 0 && value.unmatched_historical.length === 0 && !value.coverage.complete))
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
      && conditionList(item.unmatched_query_conditions)
      && validProcessComparison(item.process_comparison, result.source_case_id ?? null, item.case_id))
}
export const caseHistoryApi = {
  async read(caseId: number, signal?: AbortSignal): Promise<CaseHistoryResult> {
    const { data } = await api.get<CaseHistoryResult>('/knowledge/history', { params: { source_case_id: caseId, limit: 3 }, signal })
    if (!isCaseHistoryResult(data) || data.source_case_id !== caseId) throw new Error('历史参考来源不一致')
    return data
  },
}
