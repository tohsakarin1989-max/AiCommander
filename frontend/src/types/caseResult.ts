import type { CaseSemantics } from '../services/intelligenceFlow'

export type CaseResultCandidate = {
  id: string; rank: number; category: string; title: string; claim: string
  region: Record<string, unknown> | null
  score: number; score_kind: 'rule_support_not_probability'
  score_components: Record<string, unknown>
  evidence_refs: string[]; supporting_evidence: string[]; counter_evidence: string[]
  information_gaps: string[]; boundary: string; status: string; is_official_fact: false
}

export type CaseResult = {
  id: string; created_at: string; content_sha256: string
  freshness?: 'current' | 'pending_update'
  content: {
    schema_version: string; case_id: number
    versions: {
      case_profile_id: string; profile_version: number; case_source_hash: string
      profile_schema: string; dictionary_version: string
      analysis_run_id: string | null; map_snapshot_id: string | null; algorithm_version: string | null
    }
    facts_summary: { label: string; recorded_fields: Record<string, unknown>; evidence_refs: string[] }
    related_conditions: Record<string, unknown>; semantics: CaseSemantics | null
    candidates: CaseResultCandidate[]
    information_gaps: { profile: Array<{ label: string; reason?: string }>; analysis: string[] }
    analysis_status: string; boundary: string[]
  }
}

export type CaseResultCatalog = {
  items: Array<{
    id: string; case_id: number; case_number: string; availability: 'available' | 'unavailable'
    created_at?: string; versions?: CaseResult['content']['versions']; analysis_status?: string
  }>
  has_more: boolean; offset: number; limit: number
}
