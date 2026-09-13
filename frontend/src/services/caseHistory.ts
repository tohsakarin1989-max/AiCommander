import api from './api'

export interface HistoryReference {
  source_type: 'case' | 'experience_card' | 'legacy_experience_card'
  source_id: number; case_id: number; case_number: string; title: string; snippet: string; route: string
  shared_conditions: [string, string, string][]
  different_conditions: [string, string, string][]
  unmatched_query_conditions: [string, string, string][]
  score: number; score_kind: string; profile_state: string
  versions: Record<string, string | number | null>
}
export interface CaseHistoryResult {
  schema_version: 'case-history-5.1-1'; source_case_id: number | null
  state: 'ready' | 'partial'; mode: string; semantic_index_state: string
  coverage: { authorized_cases: number; scanned_cases: number; matched_sources: number; complete: boolean }
  items: HistoryReference[]; boundary: string
}
export function isCaseHistoryResult(value: unknown): value is CaseHistoryResult {
  if (!value || typeof value !== 'object') return false
  const result = value as Partial<CaseHistoryResult>
  const coverage = result.coverage
  const conditionList = (items: unknown) => Array.isArray(items) && items.every(item =>
    Array.isArray(item) && item.length === 3 && item.every(part => typeof part === 'string'))
  return result.schema_version === 'case-history-5.1-1' && ['ready', 'partial'].includes(result.state || '')
    && typeof result.mode === 'string' && typeof result.semantic_index_state === 'string'
    && typeof result.boundary === 'string' && !!coverage && typeof coverage.complete === 'boolean'
    && [coverage.authorized_cases, coverage.scanned_cases, coverage.matched_sources].every(n => Number.isInteger(n) && n >= 0)
    && Array.isArray(result.items) && result.items.every(item => item && typeof item === 'object'
      && ['case', 'experience_card', 'legacy_experience_card'].includes(item.source_type)
      && Number.isInteger(item.case_id) && item.case_id > 0
      && typeof item.title === 'string' && typeof item.snippet === 'string'
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
