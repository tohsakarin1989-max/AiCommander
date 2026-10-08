import api from './api'

export interface ProcessTextReference {
  field: string; source_sha256: string; start: number; end: number; quote: string; source_revision_id: number
}
export type HistoryTextReference = Omit<ProcessTextReference, 'source_revision_id'>
export type HistoryCondition = [string, string, string]
export interface HistoryContrastEvidence {
  version: 'history-contrast-8.1-1'
  current_source: { case_id: number; source_revision_id: number | null; source_text_hash: string }
    | { query: string; query_sha256: string }
  shared_conditions: Array<{ condition: HistoryCondition; current_reference: HistoryTextReference; historical_reference: HistoryTextReference }>
  different_conditions: Array<{ current_condition: HistoryCondition; historical_condition: HistoryCondition
    current_reference: HistoryTextReference; historical_reference: HistoryTextReference }>
  boundary: string
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
  purpose?: 'similar' | 'contrast'
  contrast_evidence?: HistoryContrastEvidence
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
function validHistoryTextReference(value: HistoryTextReference) {
  return !!value && typeof value.field === 'string' && /^[a-f0-9]{64}$/.test(value.source_sha256)
    && Number.isInteger(value.start) && value.start >= 0 && Number.isInteger(value.end) && value.end > value.start
    && typeof value.quote === 'string' && Array.from(value.quote).length === value.end - value.start
}
function validContrastEvidence(item: HistoryReference, sourceId: number | null): boolean {
  if (item.purpose !== 'contrast') return item.contrast_evidence === undefined
  const evidence = item.contrast_evidence
  if (!evidence || evidence.version !== 'history-contrast-8.1-1' || typeof evidence.boundary !== 'string'
      || !evidence.current_source || typeof evidence.current_source !== 'object' || !item.fragment
      || !(item.fragment.source_revision_id === null || (Number.isInteger(item.fragment.source_revision_id) && item.fragment.source_revision_id > 0))) return false
  const source = evidence.current_source
  if ('case_id' in source) {
    if (sourceId === null || source.case_id !== sourceId || !/^[a-f0-9]{64}$/.test(source.source_text_hash)
        || !(source.source_revision_id === null || (Number.isInteger(source.source_revision_id) && source.source_revision_id > 0))) return false
  } else if (typeof source.query !== 'string' || !source.query.trim() || !/^[a-f0-9]{64}$/.test(source.query_sha256)) return false
  const explicit = (value: HistoryCondition) => Array.isArray(value) && value.length === 3
    && value.every(part => typeof part === 'string' && part.length > 0) && value[0] !== 'action' && ['stated', 'negated'].includes(value[2])
  const pairReferences = (row: { current_reference: HistoryTextReference; historical_reference: HistoryTextReference }) =>
    validHistoryTextReference(row.current_reference) && validHistoryTextReference(row.historical_reference)
  return Array.isArray(evidence.shared_conditions) && evidence.shared_conditions.length > 0
    && evidence.shared_conditions.every(row => !!row && explicit(row.condition) && pairReferences(row))
    && Array.isArray(evidence.different_conditions) && evidence.different_conditions.length > 0
    && evidence.different_conditions.every(row => !!row && explicit(row.current_condition) && explicit(row.historical_condition)
      && row.current_condition[0] === row.historical_condition[0] && row.current_condition[1] === row.historical_condition[1]
      && row.current_condition[2] !== row.historical_condition[2] && pairReferences(row))
    && JSON.stringify(item.shared_conditions) === JSON.stringify(evidence.shared_conditions.map(row => row.condition))
    && JSON.stringify(item.different_conditions) === JSON.stringify(evidence.different_conditions.map(row => row.historical_condition))
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
  purpose?: 'similar' | 'contrast' | 'mixed'; degraded?: boolean
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
    && (result.purpose === undefined || ['similar', 'contrast', 'mixed'].includes(result.purpose))
    && (result.degraded === undefined || typeof result.degraded === 'boolean')
    && typeof result.mode === 'string' && typeof result.semantic_index_state === 'string'
    && typeof result.boundary === 'string' && !!coverage && typeof coverage.complete === 'boolean'
    && [coverage.authorized_cases, coverage.scanned_cases, coverage.matched_sources].every(n => Number.isInteger(n) && n >= 0)
    && (!modern || (result.retrieval_mode === 'fragment_index' && ['pending', 'partial', 'ready'].includes(result.index_state || '')
      && [coverage.indexed_cases, coverage.missing_index_cases, coverage.indexed_fragments, coverage.recalled_fragments,
        coverage.validated_fragments, coverage.invalidated_fragments, coverage.recall_limit].every(n => typeof n === 'number' && Number.isInteger(n) && n >= 0)))
    && Array.isArray(result.items) && result.items.every(item => item && typeof item === 'object'
      && (item.purpose === undefined || ['similar', 'contrast'].includes(item.purpose))
      && (result.purpose !== 'contrast' || item.purpose === 'contrast')
      && (result.purpose !== 'similar' || item.purpose !== 'contrast')
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
      && validProcessComparison(item.process_comparison, result.source_case_id ?? null, item.case_id)
      && validContrastEvidence(item, result.source_case_id ?? null))
    && (result.purpose !== 'mixed' || (result.items.length <= 3
      && result.items.filter(item => item.purpose === 'similar').length <= 2
      && result.items.filter(item => item.purpose === 'contrast').length <= 1
      && result.items.every(item => item.purpose !== undefined)
      && new Set(result.items.map(item => item.case_id)).size === result.items.length))
}
export const caseHistoryApi = {
  async read(caseId: number, signal?: AbortSignal): Promise<CaseHistoryResult> {
    const { data } = await api.get<CaseHistoryResult>('/knowledge/history', { params: { source_case_id: caseId, limit: 3, include_contrast: true }, signal })
    if (!isCaseHistoryResult(data) || data.source_case_id !== caseId) throw new Error('历史参考来源不一致')
    return data
  },
}
