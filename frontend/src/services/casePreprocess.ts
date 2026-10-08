import api from './api'

export const casePreprocessApi = {
  statuses: async (caseIds: number[]) => (await api.get<{ items: Array<{ case_id: number; status: string }> }>(
    '/cases/preprocess/profiles', { params: { case_ids: caseIds }, paramsSerializer: { indexes: null } })).data,
  result: async (caseId: number, signal?: AbortSignal) => (await api.get<{
    status: string
    data: Record<string, any> | null
    model_supplement: { status: string; payload?: { content: Record<string, any>; boundary: string } }
    legacy_features: Record<string, unknown> | null
    legacy_boundary: string
  }>(`/cases/${caseId}/preprocess-result`, { signal })).data,
}

export function profileStatusLabel(status?: string): string {
  const labels: Record<string, string> = { ready: '当前画像可用', updating: '源数据已变化，待更新', unavailable: '尚无可用画像' }
  return labels[status || '']
    || '状态待读取'
}
