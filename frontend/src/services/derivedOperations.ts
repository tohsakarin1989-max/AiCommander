import api from './api'

export type DerivedTask = {
  id: string; kind: string; label: string; status: string; attempts: number
  created_at: string; available_at: string; retryable: boolean
  source_state: 'current' | 'outdated_or_unavailable'
}
export type DerivedDirectory = {
  items: DerivedTask[]; total: number; page: number; page_size: number
  counts: Record<string, number>; oldest_wait_seconds: number | null
  worker_capacity: string; boundary: string
}
export const derivedOperations = {
  list: async (page: number, failedOnly: boolean, signal?: AbortSignal): Promise<DerivedDirectory> =>
    (await api.get('/admin/derived-tasks', { params: { page, page_size: 10, status: failedOnly ? 'failed' : undefined }, signal })).data,
  retry: async (row: DerivedTask, requestId: string, signal?: AbortSignal) =>
    (await api.post(`/admin/derived-tasks/${encodeURIComponent(row.id)}/retry`,
      { request_id: requestId, expected_attempts: row.attempts }, { signal })).data,
}
