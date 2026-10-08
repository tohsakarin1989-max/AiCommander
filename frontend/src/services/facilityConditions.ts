import type { FacilityTemporalContext } from './facilityAnalysis'
import type { RegionalSelection } from './regionalContext'

export type FacilityConditionState = 'hard_excluded' | 'different' | 'unknown' | 'supported'
export interface FacilityConditionComparison {
  schema_version: 'facility-conditions-6.3-1'
  rows: Array<{
    asset_id: number; name: string; eligibility: 'retained' | 'excluded' | 'unresolved'; rank: number | null; score: number | null
    conditions: Array<{ key: string; label: string; state: FacilityConditionState; reason: string; evidence_refs: string[]; dependencies: string[] }>
    source_context: { valid_at: string | null; known_at: string; version_id: number | null; state: string }
      & Pick<FacilityTemporalContext, 'query_interval' | 'knowledge_mode' | 'coverage' | 'late_supplement' | 'groups'>
    boundary: string
  }>
  priority_gaps: Array<{ key: string; label: string; asset_ids: number[]; condition_keys: string[]; dependencies: string[]; reason: string
    ranking_version?: 'facility-gap-impact-7.5-1'
    priority_basis?: { blocked_candidates: number; unresolved_candidates: number; ranked_candidates: number; affected_candidates: number }
    impacts?: Array<{ asset_id: number; name: string; eligibility: 'retained' | 'unresolved'; blocks_comparison: boolean; reason: string; evidence_refs: string[] }> }>
  boundary: string
}

export function facilityConditionTimeContext(context: FacilityConditionComparison['rows'][number]['source_context'] | undefined, resultRef: string): RegionalSelection {
  const interval = context?.query_interval
  const base: RegionalSelection = { valid_at: null, valid_from: null, valid_to: null, known_at: null, knowledge_mode: null, time_scope: 'unknown', resultRef }
  if (!context?.known_at || (!context.valid_at && !interval)) return base
  // Re-reading a frozen result must use its recorded knowledge cutoff, even if
  // that result was originally made by looking back from its creation time.
  return { ...base, valid_at: interval ? null : context.valid_at, valid_from: interval?.from ?? null, valid_to: interval?.to ?? null,
    known_at: context.known_at, knowledge_mode: 'as_known', time_scope: 'frozen_result' }
}
export interface FacilityRankingChanges {
  state: 'no_baseline' | 'not_comparable' | 'compared'
  baseline: { artifact_id: string; content_sha256: string } | null
  changes: Array<{ asset_id: number; name: string; previous_rank: number | null; current_rank: number | null
    changed_conditions: Array<{ key: string; previous_state: string | null; current_state: string | null; evidence_refs: string[]; previous_evidence_refs?: string[] }>; reasons: string[] }>
  context_changes: string[]; boundary: string
}

function validGapImpacts(gap: FacilityConditionComparison['priority_gaps'][number], rows: FacilityConditionComparison['rows']): boolean {
  if (gap.ranking_version === undefined) return gap.priority_basis === undefined && gap.impacts === undefined
  if (gap.ranking_version !== 'facility-gap-impact-7.5-1' || !gap.priority_basis || !Array.isArray(gap.impacts)) return false
  const basis = gap.priority_basis, impacts = gap.impacts
  return Object.values(basis).every(n => Number.isInteger(n) && n >= 0)
    && impacts.length === gap.asset_ids.length && new Set(gap.asset_ids).size === impacts.length
    && new Set(impacts.map(item => item.asset_id)).size === impacts.length
    && basis.affected_candidates === impacts.length
    && basis.blocked_candidates === impacts.filter(item => item.blocks_comparison).length
    && basis.unresolved_candidates === impacts.filter(item => item.eligibility === 'unresolved').length
    && basis.ranked_candidates === impacts.filter(item => item.eligibility === 'retained').length
    && impacts.every(item => {
      const row = rows.find(row => row.asset_id === item.asset_id)
      const condition = row?.conditions.find(condition => condition.key === gap.key)
      if (!row || !condition) return false
      return gap.asset_ids.includes(item.asset_id) && row.name === item.name && condition.state === 'unknown'
        && typeof item.blocks_comparison === 'boolean' && ['retained', 'unresolved'].includes(item.eligibility)
        && row.eligibility === item.eligibility && condition.reason === item.reason
        && item.blocks_comparison === (gap.key === 'road' && item.eligibility === 'unresolved')
        && Array.isArray(item.evidence_refs) && item.evidence_refs.length > 0
        && JSON.stringify(item.evidence_refs) === JSON.stringify(condition.evidence_refs)
    })
}

export function validFacilityConditions(value: FacilityConditionComparison, recalled: number): boolean {
  const textList = (v: unknown) => Array.isArray(v) && v.every(x => typeof x === 'string')
  const id = (v: unknown) => typeof v === 'number' && Number.isInteger(v) && v > 0
  return value?.schema_version === 'facility-conditions-6.3-1' && typeof value.boundary === 'string'
    && Array.isArray(value.rows) && value.rows.length === recalled && new Set(value.rows.map(row => row.asset_id)).size === recalled
    && value.rows.every(row => id(row.asset_id) && typeof row.name === 'string'
      && ['retained', 'excluded', 'unresolved'].includes(row.eligibility) && (row.rank === null || id(row.rank))
      && (row.score === null || (typeof row.score === 'number' && Number.isFinite(row.score)))
      && typeof row.boundary === 'string' && !!row.source_context && typeof row.source_context.state === 'string'
      && Array.isArray(row.conditions) && row.conditions.every(condition =>
        ['hard_excluded', 'different', 'unknown', 'supported'].includes(condition.state)
        && [condition.key, condition.label, condition.reason].every(v => typeof v === 'string')
        && textList(condition.evidence_refs) && textList(condition.dependencies)))
    && Array.isArray(value.priority_gaps) && value.priority_gaps.every(gap =>
      [gap.key, gap.label, gap.reason].every(v => typeof v === 'string') && textList(gap.dependencies)
      && textList(gap.condition_keys) && Array.isArray(gap.asset_ids) && gap.asset_ids.every(id)
      && validGapImpacts(gap, value.rows))
}

export function validRankingChanges(value: FacilityRankingChanges): boolean {
  return ['no_baseline', 'not_comparable', 'compared'].includes(value?.state)
    && typeof value.boundary === 'string' && Array.isArray(value.context_changes) && value.context_changes.every(v => typeof v === 'string')
    && (value.baseline === null || (typeof value.baseline?.artifact_id === 'string' && /^[a-f0-9]{64}$/.test(value.baseline.content_sha256)))
    && Array.isArray(value.changes) && value.changes.every(change => Number.isInteger(change.asset_id) && change.asset_id > 0
      && typeof change.name === 'string' && [change.previous_rank, change.current_rank].every(rank => rank === null || (Number.isInteger(rank) && rank > 0))
      && Array.isArray(change.reasons) && change.reasons.every(v => typeof v === 'string')
      && Array.isArray(change.changed_conditions) && change.changed_conditions.every(condition =>
        typeof condition.key === 'string' && [condition.previous_state, condition.current_state].every(v => v === null || typeof v === 'string')
        && Array.isArray(condition.evidence_refs) && condition.evidence_refs.every(v => typeof v === 'string')))
}
