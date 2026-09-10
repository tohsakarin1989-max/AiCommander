import api from './api'

export interface RoadFeature {
  type: 'Feature'
  id: string
  geometry: { type: string; coordinates: unknown }
  properties: { name: string; kind: 'road' | 'entrance'; road_id?: string; conditions?: Record<string, unknown> }
}
export interface RoadReview {
  id: number
  decision: 'verified' | 'rejected' | 'pending_verification'
  note: string
  evidence_reference: string
  created_by: number
  created_at: string
}
export interface RoadImport {
  id: number
  input_sha256: string
  features: RoadFeature[]
  feature_reviews?: Record<string, RoadReview | null>
  warnings: Array<{ source_feature_id: string; warnings: string[] }>
}
export interface RoadPreview {
  total: number
  valid: number
  rows: Array<{ row: number; source_feature_id: string | null; errors: string[]; warnings: string[] }>
}
export interface RoadImportPage {
  items: Array<{ id: number; created_at: string; feature_count: number }>
  next_before_id: number | null
}
const root = (source: number) => `/map-sources/${source}/roads`
export const internalRoadsApi = {
  preview: async (source: number, payload: unknown) =>
    (await api.post<RoadPreview>(`${root(source)}/preview`, payload)).data,
  ingest: async (source: number, payload: unknown) =>
    (await api.post<RoadImport>(`${root(source)}/ingest`, payload)).data,
  list: async (source: number, before?: number, signal?: AbortSignal) =>
    (await api.get<RoadImportPage>(`${root(source)}/imports`, { params: { before_id: before, limit: 20 }, signal })).data,
  read: async (source: number, id: number, signal?: AbortSignal) =>
    (await api.get<RoadImport>(`${root(source)}/imports/${id}`, { signal })).data,
  review: async (source: number, record: RoadImport, feature: RoadFeature, decision: RoadReview['decision'], note: string, evidence: string) =>
    (await api.post<RoadReview>(`${root(source)}/imports/${record.id}/features/${encodeURIComponent(feature.id)}/reviews`, {
      input_sha256: record.input_sha256, request_key: crypto.randomUUID(),
      previous_review_id: record.feature_reviews?.[feature.id]?.id ?? null,
      decision, note, evidence_reference: evidence,
    })).data,
}
