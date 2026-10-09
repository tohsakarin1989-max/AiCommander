import api from './api'

export type MapIssueGroup = 'identity' | 'coordinates' | 'water_cut' | 'production' | 'other'
export interface MapIssueReference {
  field_group: MapIssueGroup
  source_claim_id?: number | null
  asset_version_id?: number | null
}
export interface MapDataIssue {
  id: number; asset_id: number; notes: string; source_reference: MapIssueReference
  state: 'reported' | 'needs_information' | 'checked_no_change' | 'corrected'; created_at: string | null
  asset_name?: string
  resolution?: { state: string; note: string; source_reference: MapIssueReference | null; resolved_at: string } | null
}
export const mapDataIssuesApi = {
  async work(sourceId?: number, page = 1, signal?: AbortSignal) {
    return (await api.get<{ items: MapDataIssue[]; total: number; page: number; page_size: number }>(
      '/map-data-issues', { params: { source_id: sourceId, page, page_size: 10 }, signal })).data
  },
  async resolve(id: number, payload: { state: string; expected_state: string; note: string; request_id: string; source_reference?: MapIssueReference }) {
    return (await api.post<MapDataIssue>(`/map-data-issues/${id}/resolve`, payload)).data
  },
  async list(assetId: number, page: number, signal?: AbortSignal) {
    const { data } = await api.get<{ items: MapDataIssue[]; total: number; page: number; page_size: number; boundary: string }>(
      '/jurisdiction/data-issues', { params: { asset_id: assetId, page, page_size: 10 }, signal },
    )
    return data
  },
  async create(assetId: number, notes: string, sourceReference: MapIssueReference) {
    const { data } = await api.post('/jurisdiction/feedback', {
      feedback_type: 'data_issue', asset_id: assetId, notes, source_reference: sourceReference,
    })
    return data
  },
  async original(runId: string) {
    const { data } = await api.get<Blob>(`/map-ingest-runs/${encodeURIComponent(runId)}/original`, { responseType: 'blob' })
    return data
  },
}
