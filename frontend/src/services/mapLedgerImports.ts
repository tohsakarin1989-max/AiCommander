import api from './api'
import type { MapImportTemplate, MapIngestRun, MapPreview, MapLedgerDeclaration } from './mapFoundation'

export type MapRowClassification = 'new' | 'updated' | 'unchanged' | 'identity_pending' | 'conflict' | 'failed'
export interface MapImportField { key: string; label: string; type: string; description: string; group: string | null; required: boolean }
export interface MapFieldContract { schema_version: string; fields: MapImportField[]; groups: Record<string, string[]>; value_states: string[] }
export interface MapImportStructure { headers: string[]; sheet_name: string | null; header_row: number }
export interface MapPlanRow {
  row_number: number; classification: MapRowClassification; asset_id: number | null; asset_version: number | null
  changes: Array<{ field: string; old: unknown; new: unknown }>
  groups: Array<{ group: string; state: string; status: string; reason: string; old: Record<string, unknown>; new: Record<string, unknown> }>
  errors: Array<{ field: string; code: string; message: string }>
}
export interface MapLedgerPreview extends MapPreview {
  ledger_declaration?: MapLedgerDeclaration | null
  ledger_comparison?: MapLedgerComparison
  plan_token: string
  counts: Record<MapRowClassification, number>
  rows: MapPlanRow[]
  rows_complete?: boolean
  structure: MapImportStructure
  drift: Array<{ field: string; code: string; message: string; old?: unknown; new?: unknown }>
}
export interface MapLedgerRun extends MapIngestRun {
  ledger_declaration?: MapLedgerDeclaration | null
  declaration_actor_id?: number | null
  started_at?: string | null
  completed_at?: string | null
  table_metadata: MapImportStructure | null
  template_snapshot: MapImportTemplate | null
  counts: Record<MapRowClassification, number>
  parent_run_id: string | null
  original_evidence_object_id: number | null
}
export interface MapLedgerComparison {
  status: 'comparable' | 'not_comparable'; reason: string; phase: 'preview' | 'executed'; boundary: string
  baseline_run_id?: string; baseline_source_revision?: string; baseline_declaration?: MapLedgerDeclaration
  missing?: Array<{ source_record_id: string; claim_id: number; asset_id: number; row_number: number }>
  missing_count?: number; previous_count?: number; current_count?: number; rows_complete?: boolean
}
export interface MapLedgerClaim {
  id: number; run_id: string; row_number: number; status: string; source_record_id: string | null
  raw_payload: Record<string, unknown> | null; normalized_payload: Record<string, unknown> | null
  plan: MapPlanRow | null; parent_claim_id: number | null; correction_note: string | null
  source_identity_id: number | null; identity_decision_id: number | null
  retry_superseded?: boolean
}
export interface MapRetryRequest { request_id: string; template_id?: number; rows: Array<{ claim_id: number; values: Record<string, unknown> }>; plan_token?: string }
export type MapFieldGroup = 'geometry' | 'water_cut' | 'production' | 'details'
export interface MapFieldDecisionPreview {
  asset_id: number; asset_version: number; decision_id: number | null; group: MapFieldGroup; state: string
  candidate: Record<string, unknown>; current: Record<string, unknown>; source_id: number; can_resolve: boolean; boundary: string
}
export interface MapFieldDecisionRequest {
  group: MapFieldGroup; request_id: string; note: string; expected_asset_version: number; expected_decision_id: number | null
}
export interface OffsetPage<T> { items: T[]; total: number; offset: number; limit: number }
export const mapLedgerImportsApi = {
  fields: async (signal?: AbortSignal): Promise<MapFieldContract> => (await api.get('/map-import-fields', { signal })).data,
  example: async (): Promise<Blob> => (await api.get('/map-import-example', { responseType: 'blob' })).data,
  preview: async (sourceId: number, file: File, templateId?: number, signal?: AbortSignal, declaration?: MapLedgerDeclaration): Promise<MapLedgerPreview> => {
    const data = new FormData(); data.append('file', file)
    if (declaration) data.append('ledger_declaration', JSON.stringify(declaration))
    return (await api.post(`/map-sources/${sourceId}/preview`, data, { params: { template_id: templateId }, headers: { 'Content-Type': 'multipart/form-data' }, signal })).data
  },
  runs: async (sourceId: number, offset = 0, signal?: AbortSignal): Promise<OffsetPage<MapLedgerRun>> =>
    (await api.get('/map-ingest-runs', { params: { source_id: sourceId, offset, limit: 10 }, signal })).data,
  claims: async (runId: string, offset = 0, classification?: MapRowClassification, signal?: AbortSignal): Promise<OffsetPage<MapLedgerClaim>> =>
    (await api.get(`/map-ingest-runs/${encodeURIComponent(runId)}/claims`, { params: { offset, limit: 20, classification }, signal })).data,
  retryPreview: async (runId: string, payload: MapRetryRequest): Promise<MapLedgerPreview> =>
    (await api.post(`/map-ingest-runs/${encodeURIComponent(runId)}/retry-preview`, payload)).data,
  retry: async (runId: string, payload: MapRetryRequest): Promise<MapLedgerRun> =>
    (await api.post(`/map-ingest-runs/${encodeURIComponent(runId)}/retry`, payload)).data,
  comparison: async (runId: string, signal?: AbortSignal): Promise<MapLedgerComparison> =>
    (await api.get(`/map-ingest-runs/${encodeURIComponent(runId)}/ledger-comparison`, { signal })).data,
  original: async (runId: string): Promise<Blob> =>
    (await api.get(`/map-ingest-runs/${encodeURIComponent(runId)}/original`, { responseType: 'blob' })).data,
  fieldDecisionPreview: async (claimId: number, group: MapFieldGroup, signal?: AbortSignal): Promise<MapFieldDecisionPreview> =>
    (await api.get(`/map-conflicts/${claimId}/field-decision-preview`, { params: { group }, signal })).data,
  fieldDecision: async (claimId: number, payload: MapFieldDecisionRequest): Promise<MapLedgerRun> =>
    (await api.post(`/map-conflicts/${claimId}/field-decision`, payload)).data,
}
