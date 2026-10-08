export interface AttentionEvidence {
  case_ids?: number[]
  value?: string
  label?: string
  relation_kind?: string
  independent_count?: number
  distance_km?: number
  location_role?: string
  evidence_refs?: string[]
  references?: Array<{ case_id: number; profile_id: string; source_revision_id: number | null; reference: { quote?: string; field?: string } }>
}
export interface AttentionLayer {
  state: string; items?: AttentionEvidence[]; record_count?: number; raw_record_count?: number
  gaps: string[]; boundary: string
}
export interface AttentionItem {
  object_key: string; object_type: 'area' | 'facility'; object_id: number; label: string
  state: 'repeated_conditions' | 'new_information' | 'background_only'
  support_record_count: number
  layers: Partial<Record<'explicit_links' | 'spatial_proximity' | 'condition_similarity' | 'production_background', AttentionLayer>>
  evidence_refs: string[]; gaps: string[]; boundary: string
}
export interface AttentionGrounding {
  version: string; items: AttentionItem[]; boundary: string
  coverage: { state?: string; cases_scanned: number; facilities_scanned?: number; independent_records?: number; selection: string; complete?: boolean }
}
