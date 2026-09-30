import api from './api'

export const resultKinds = { case: '案件成果', topic: '专题材料', facility: '设施材料', situation: '态势简报', meeting: '会议报告', query: '助手查询', experience: '经验与历史报告', conclusion: '历史结论' } as const
export type ResultKind = keyof typeof resultKinds
export type ResultSource = { kind: ResultKind; id: string; content_sha256: string }
export interface ResultItem extends ResultSource {
  title: string; created_at: string; schema_version: string; subject: { kind: string; id: string | number }
  availability: 'available'
}
export type JudgmentDecision = 'confirm' | 'retain_reference' | 'insufficient_evidence' | 'exclude_with_evidence'
export interface ResultJudgment {
  id: string; decision: JudgmentDecision; note: string; created_at: string; created_by: number
  content_sha256: string; additional_sources: ResultSource[]
}
export interface ResultMaterial extends ResultItem {
  body: Record<string, unknown>; sources: ResultSource[]; boundary: string[]
  document: { schema_version: string; blocks: { kind: 'heading' | 'paragraph' | 'table' | 'source' | 'map'; text: string; rows: string[][] }[] }
  judgments: ResultJudgment[]
  experience_review?: { status: string; reviewer_label?: string; review_note?: string; reviewed_at?: string }
  map?: { state: string; reason?: string; map_snapshot_id?: string; point_count?: number }
}
export const isResultKind = (value: string | null): value is ResultKind => !!value && Object.prototype.hasOwnProperty.call(resultKinds, value)
export const resultPath = (kind: ResultKind, id: string | number) => `/reports?kind=${kind}&resultId=${encodeURIComponent(String(id))}`
export const materialRequestKey = () => crypto.randomUUID()
export const resultsApi = {
  list: async (params: { q?: string; kind?: ResultKind; offset?: number; limit?: number; subject_kind?: string; subject_id?: string }, signal?: AbortSignal) =>
    (await api.get<{ items: ResultItem[]; has_more: boolean; offset: number; limit: number }>('/results', { params, signal })).data,
  read: async (kind: ResultKind, id: string, signal?: AbortSignal) => {
    const { data } = await api.get<ResultMaterial>(`/results/${kind}/${encodeURIComponent(id)}`, { signal })
    if (data.kind !== kind || String(data.id) !== id || !/^[a-f0-9]{64}$/.test(data.content_sha256) || !Array.isArray(data.document?.blocks)) throw new Error('material_contract_invalid')
    return data
  },
  document: async (item: ResultSource, format: 'docx' | 'pdf', signal?: AbortSignal) => {
    const response = await api.get<Blob>(`/results/${item.kind}/${encodeURIComponent(item.id)}/document.${format}`, { responseType: 'blob', signal })
    if (response.headers['x-result-content-sha256'] !== item.content_sha256) throw new Error('material_version_changed')
    return response.data
  },
  freezeFacility: async (assetId: number, payload: { start_date?: string; end_date?: string; valid_at?: string; known_at?: string; idempotency_key: string }) =>
    (await api.post<ResultMaterial>(`/results/facilities/${assetId}`, payload)).data,
  mapImage: async (item: ResultSource, signal?: AbortSignal) => {
    const response = await api.get<Blob>(`/results/${item.kind}/${encodeURIComponent(item.id)}/map.png`, { responseType: 'blob', signal })
    if (response.headers['x-result-content-sha256'] !== item.content_sha256) throw new Error('material_version_changed')
    return response.data
  },
  judge: async (item: ResultSource, payload: { decision: JudgmentDecision; note: string; additional_sources: ResultSource[]; idempotency_key: string }) =>
    (await api.post<ResultMaterial>(`/results/${item.kind}/${encodeURIComponent(item.id)}/judgments`, { ...payload, content_sha256: item.content_sha256 })).data,
}
