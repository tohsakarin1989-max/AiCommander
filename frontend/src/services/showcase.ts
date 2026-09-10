import api from './api'

export type ShowcaseScenario = 'normal' | 'missing_location' | 'model_unavailable'
export interface ShowcaseRecord {
  id: string
  status: string
  scenario: ShowcaseScenario
  created_at: string
  completed_at: string | null
  view_kind: 'live_result' | 'historical_replay'
  error: string | null
  result: {
    dataset_version?: string
    input_digest?: string
    boundary?: string
    original_facts_unchanged?: boolean
    import?: { filename: string; rows: number; field_mapping: Record<string, string>; csv: string; sha256: string; time_zone: string }
    case?: { description: string; location: string; occurred_time: string; latitude: number | null; longitude: number | null }
    map_features?: { name: string; latitude: number; longitude: number }[]
    profile?: { id: string; schema_version: string; dictionary_version: string; quality_score: number; payload: Record<string, unknown> }
    analysis?: { id: string; status: string; algorithm_version: string; summary: string; information_gaps: string[];
      hypotheses: { id: string; title: string; claim: string; score: number; evidence_refs: string[];
        supporting_evidence: string[]; counter_evidence: string[]; information_gaps: string[]; boundary: string }[] }
    brief?: { summary: string; evidence_refs: string[]; information_gaps: string[] }
    fault?: { kind: string; status: string; calls: number; fallback_mode: string } | null
    trace?: { sequence: number; service: string; duration_ms: number; call_status: string; result_status: string }[]
  }
}
export const showcaseApi = {
  history: async (signal?: AbortSignal): Promise<{ items: ShowcaseRecord[] }> => (await api.get('/showcase/runs', { signal })).data,
  read: async (id: string): Promise<ShowcaseRecord> => (await api.get(`/showcase/runs/${encodeURIComponent(id)}`)).data,
  create: async (scenario: ShowcaseScenario, requestId: string): Promise<ShowcaseRecord> =>
    (await api.post('/showcase/runs', { scenario, request_id: requestId })).data,
}
