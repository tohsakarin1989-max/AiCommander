import api from './api'

export interface CaseDraft {
  id: string
  revision: number
  status: string
  operational_area_id: number
  target_case_id: number | null
  base_case_revision: number | null
  schema_version: number
  form_snapshot: Record<string, unknown>
  updated_at: string
  expires_at: string
  submission_key: string
  submitted_case_id: number | null
}

export interface CaseDraftSave {
  expected_revision: number
  operational_area_id: number
  target_case_id?: number | null
  base_case_revision?: number | null
  schema_version: 1
  form_snapshot: Record<string, unknown>
}

export const caseDraftsApi = {
  list: async (page = 1, signal?: AbortSignal): Promise<{ items: CaseDraft[]; total: number; page: number; page_size: number }> =>
    (await api.get('/case-drafts', { params: { page, page_size: 20, status: 'all' }, signal })).data,
  get: async (id: string, signal?: AbortSignal): Promise<CaseDraft> =>
    (await api.get(`/case-drafts/${encodeURIComponent(id)}`, { signal })).data,
  save: async (id: string, payload: CaseDraftSave): Promise<CaseDraft> =>
    (await api.put(`/case-drafts/${encodeURIComponent(id)}`, payload)).data,
  submit: async (id: string, expectedRevision: number, payload: unknown, confirmOnly = false): Promise<{ case_id: number }> =>
    (await api.post(`/case-drafts/${encodeURIComponent(id)}/submit`, { expected_revision: expectedRevision, case_payload: payload,
      ...(confirmOnly ? { confirm_only: true } : {}) })).data,
  remove: async (id: string, revision: number): Promise<void> => {
    await api.delete(`/case-drafts/${encodeURIComponent(id)}`, { params: { expected_revision: revision } })
  },
}
