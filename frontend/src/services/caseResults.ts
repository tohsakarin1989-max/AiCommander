import api from './api'
import type { CaseResult, CaseResultCatalog } from '../types/caseResult'

export const caseResultsApi = {
  download: async (resultId: string, hash: string, format: 'docx' | 'pdf', signal: AbortSignal,
    road?: { id: string; content_sha256: string }): Promise<Blob> => {
    const response = await api.get<Blob>(`/case-results/${encodeURIComponent(resultId)}/document.${format}`, {
      responseType: 'blob', signal, timeout: 180000,
      ...(road ? { params: { road_artifact_id: road.id } } : {}),
    })
    const expectedType = format === 'pdf' ? 'application/pdf'
      : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    if (!/^[a-f0-9]{64}$/.test(hash) || response.headers['x-result-content-sha256'] !== hash
      || response.data.type.split(';')[0] !== expectedType || !response.data.size || response.data.size > 20 * 1024 * 1024) {
      throw new Error('下载文件格式或成果版本不一致，请刷新成果后重试。')
    }
    if (road && (response.headers['x-road-artifact-id'] !== road.id
        || response.headers['x-road-artifact-sha256'] !== road.content_sha256)) {
      throw new Error('下载道路成果版本不一致，请刷新历史列表后重试。')
    }
    return response.data
  },
  list: async (params: { q?: string; offset?: number; limit?: number } = {}): Promise<CaseResultCatalog> => {
    const response = await api.get<CaseResultCatalog>('/case-results', { params })
    return response.data
  },
  latest: async (caseId: number): Promise<CaseResult> => {
    const response = await api.get<CaseResult>(`/cases/${caseId}/results/latest`)
    return response.data
  },
  get: async (resultId: string): Promise<CaseResult> => {
    const response = await api.get<CaseResult>(`/case-results/${encodeURIComponent(resultId)}`)
    return response.data
  },
}
