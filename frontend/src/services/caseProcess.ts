import type { SemanticReference } from './intelligenceFlow'

export type ProcessTextReference = SemanticReference & {
  kind: 'text'; source_revision_id: number | null; snapshot_path: Array<string | number>
}
export type ProcessStructuredReference = {
  kind: 'structured'; source_revision_id: number | null; source_sha256: string
  snapshot_path: Array<string | number>; value: unknown
}
export interface CaseProcess {
  version: string; source_revision_id: number | null; source_hash: string | null
  events: Array<{
    id: string; statement_kind: string; judgment_status: string
    reference: ProcessTextReference; relation_status: string; missing_dimensions: string[]
    actions: Array<{ value: string; kind: string; reference: ProcessTextReference; is_official_fact: false }>
    objects: Array<{ category: string; value: string; kind: string; reference: ProcessTextReference }>
    time_intervals: Array<{ start: string; end: string; start_precision: string; end_precision: string; timezone: string | null; reference: ProcessTextReference }>
    locations: Array<{ value: string; role: string; kind: string; reference: ProcessTextReference }>
    measurements: Array<{ value: number; unit: string; oil_type: string; kind: string; stage: 'unknown'; reference: ProcessTextReference }>; is_official_fact: false
  }>
  relations: Array<{ id: string; type: string; from_event_id: string; to_event_id: string; kind: string; reference: ProcessTextReference }>
  conflicts: Array<{ id: string; category: string; value: string; event_ids: string[]; references: ProcessTextReference[]; status: string }>
  gaps: Array<{ code: string; event_id?: string; dimension?: string; reference?: ProcessTextReference }>
  structured_context: {
    locations: Array<{ role: string; description: string | null; precision: string | null; geometry: unknown; source_note: string | null; reference: ProcessStructuredReference; binding_status: string }>
    measurements: Array<{ value: number | null; unit: string | null; stage: string | null; method: string | null; measured_at: string | null; water_cut: number | null; water_cut_basis: string | null; source_note: string | null; reference: ProcessStructuredReference; binding_status: string }>
  }
  coverage: { state: string; limit: number; omitted_fragments: number }
  boundary: string
}
