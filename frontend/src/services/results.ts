import api from './api'
import { caseContextPath } from './caseContext'
import { safeBusinessReturn } from './businessNavigation'

export const resultKinds = { case: '案件成果', topic: '专题材料', facility: '设施材料', situation: '态势简报', meeting: '会议报告', query: '助手查询', experience: '经验与历史报告', conclusion: '历史结论' } as const
export type ResultKind = keyof typeof resultKinds
export const materialTemplates = { full: '完整资料', case_summary: '案件资料摘要', facility_sheet: '设施资料单', period_brief: '周期情况材料' } as const
export type MaterialTemplate = keyof typeof materialTemplates
export const materialSections = { facts: '事实与记录', evidence: '支持依据', differences: '差异与反向情况', gaps: '资料缺口', boundary: '适用边界', map: '同源地图' } as const
export type MaterialSection = keyof typeof materialSections
export function parseMaterialSections(values: string[]): MaterialSection[] | undefined {
  if (!values.length || values.length > 6 || new Set(values).size !== values.length
    || values.some(value => !Object.prototype.hasOwnProperty.call(materialSections, value))) return undefined
  return (Object.keys(materialSections) as MaterialSection[]).filter(key => values.includes(key))
}
export type MaterialPresentationOptions = { template?: MaterialTemplate; expectedContentSha256?: string; sections?: MaterialSection[] }
export const isMaterialTemplate = (value: string | null): value is MaterialTemplate => !!value && Object.prototype.hasOwnProperty.call(materialTemplates, value)
export const isMaterialTemplateApplicable = (kind: ResultKind, template: MaterialTemplate) => template === 'full'
  || ({ case: 'case_summary', facility: 'facility_sheet', situation: 'period_brief' } as Partial<Record<ResultKind, MaterialTemplate>>)[kind] === template
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
  presentation: { template: MaterialTemplate; schema_version: string; label: string; options: { id: MaterialTemplate; label: string }[]; boundary: string
    sections?: MaterialSection[]; sections_customized?: boolean; section_options?: { id: MaterialSection; label: string }[]; sections_boundary?: string }
  judgments: ResultJudgment[]
  experience_review?: { status: string; reviewer_label?: string; review_note?: string; reviewed_at?: string }
  map?: { state: string; reason?: string; map_snapshot_id?: string; point_count?: number }
}
export const isResultKind = (value: string | null): value is ResultKind => !!value && Object.prototype.hasOwnProperty.call(resultKinds, value)
export function materialCatalogParams(context?: URLSearchParams) {
  const params = new URLSearchParams(context ? caseContextPath('/reports', context).split('?')[1] : '')
  params.delete('assetId')
  for (const name of ['meetingId', 'subject', 'subjectId', 'catalogQ', 'catalogKind', 'catalogOffset']) {
    const value = context?.get(name)
    if (value) params.set(name, value)
  }
  const back = safeBusinessReturn(context?.get('return_to') ?? null)
  if (back) params.set('return_to', back)
  return params
}
export function resultPath(kind: ResultKind, id: string | number, context?: URLSearchParams, presentation?: MaterialPresentationOptions) {
  const params = new URLSearchParams({ kind, resultId: String(id) })
  materialCatalogParams(context).forEach((value, name) => params.append(name, value))
  if (presentation?.template) params.set('template', presentation.template)
  if (presentation?.expectedContentSha256) params.set('expected_content_sha256', presentation.expectedContentSha256)
  presentation?.sections?.forEach(section => params.append('sections', section))
  return `/reports?${params}`
}
export function materialCatalogPath(context?: URLSearchParams) {
  const params = materialCatalogParams(context).toString()
  return `/reports${params ? `?${params}` : ''}`
}
export function materialSourcePath(source: ResultSource, current: ResultSource, context?: URLSearchParams) {
  const params = new URLSearchParams(resultPath(source.kind, source.id, context).split('?')[1])
  params.set('fromKind', current.kind); params.set('fromId', current.id)
  const template = context?.get('template') || 'full'
  if (isMaterialTemplate(template) && isMaterialTemplateApplicable(current.kind, template)) params.set('fromTemplate', template)
  if (/^[a-f0-9]{64}$/.test(current.content_sha256)) params.set('fromContentSha256', current.content_sha256)
  parseMaterialSections(context?.getAll('sections') || [])?.forEach(section => params.append('fromSections', section))
  return `/reports?${params}`
}
export function materialFilename(material: ResultItem, format: 'docx' | 'pdf', template: MaterialTemplate = 'full') {
  const title = material.title.replace(/[\\/:*?"<>|\u0000-\u001f\u007f]/g, '_').trim().replace(/[. ]+$/g, '').slice(0, 90) || '未命名材料'
  const date = /^\d{4}-\d{2}-\d{2}/.exec(material.created_at)?.[0] || '日期待核'
  return `${resultKinds[material.kind]}-${title}-${date}-${material.content_sha256.slice(0, 8)}${template === 'full' ? '' : `-${materialTemplates[template]}`}.${format}`
}
export const materialRequestKey = () => crypto.randomUUID()
export const resultsApi = {
  list: async (params: { q?: string; kind?: ResultKind; offset?: number; limit?: number; subject_kind?: string; subject_id?: string }, signal?: AbortSignal) =>
    (await api.get<{ items: ResultItem[]; has_more: boolean; offset: number; limit: number }>('/results', { params, signal })).data,
  read: async (kind: ResultKind, id: string, signal?: AbortSignal, options: MaterialPresentationOptions = {}) => {
    const template = options.template || 'full'
    if (!isMaterialTemplate(template) || !isMaterialTemplateApplicable(kind, template)) throw new Error('material_template_not_applicable')
    const sections = options.sections === undefined ? undefined : parseMaterialSections(options.sections)
    if (options.sections !== undefined && !sections) throw new Error('material_sections_invalid')
    const { data } = await api.get<ResultMaterial>(`/results/${kind}/${encodeURIComponent(id)}`, {
      signal, params: { template, expected_content_sha256: options.expectedContentSha256 },
      ...(sections ? { params: { template, expected_content_sha256: options.expectedContentSha256, sections }, paramsSerializer: { indexes: null } } : {}),
    })
    if (data.kind !== kind || String(data.id) !== id || !/^[a-f0-9]{64}$/.test(data.content_sha256) || !Array.isArray(data.document?.blocks)) throw new Error('material_contract_invalid')
    if (options.expectedContentSha256 && data.content_sha256 !== options.expectedContentSha256) throw new Error('material_version_changed')
    if (data.presentation?.template !== template || !data.presentation.schema_version || !data.presentation.label || !data.presentation.boundary
      || !Array.isArray(data.presentation.options) || !data.presentation.options.some(option => option.id === template)
      || data.presentation.options.some(option => !isMaterialTemplate(option.id) || !isMaterialTemplateApplicable(kind, option.id) || !option.label)) throw new Error('material_template_invalid')
    if (sections && (!data.presentation.sections_customized || data.presentation.sections?.join(',') !== sections.join(','))) throw new Error('material_sections_invalid')
    return data
  },
  document: async (item: ResultSource, format: 'docx' | 'pdf', signal?: AbortSignal, options: MaterialPresentationOptions = {}) => {
    const template = options.template || 'full'
    if (!isMaterialTemplate(template) || !isMaterialTemplateApplicable(item.kind, template)) throw new Error('material_template_not_applicable')
    const sections = options.sections === undefined ? undefined : parseMaterialSections(options.sections)
    if (options.sections !== undefined && !sections) throw new Error('material_sections_invalid')
    const response = await api.get<Blob>(`/results/${item.kind}/${encodeURIComponent(item.id)}/document.${format}`, {
      responseType: 'blob', signal, params: { template, expected_content_sha256: item.content_sha256 },
      ...(sections ? { params: { template, expected_content_sha256: item.content_sha256, sections }, paramsSerializer: { indexes: null } } : {}),
    })
    if (response.headers['x-result-content-sha256'] !== item.content_sha256) throw new Error('material_version_changed')
    if (response.headers['x-result-template'] !== template) throw new Error('material_template_invalid')
    if (sections && response.headers['x-result-sections'] !== sections.join(',')) throw new Error('material_sections_invalid')
    return response.data
  },
  freezeFacility: async (assetId: number, payload: { start_date?: string; end_date?: string; valid_at?: string; known_at?: string; valid_from?: string; valid_to?: string; knowledge_mode?: 'as_known' | 'retrospective'; idempotency_key: string }) =>
    (await api.post<ResultMaterial>(`/results/facilities/${assetId}`, payload)).data,
  mapImage: async (item: ResultSource, signal?: AbortSignal) => {
    const response = await api.get<Blob>(`/results/${item.kind}/${encodeURIComponent(item.id)}/map.png`, { responseType: 'blob', signal })
    if (response.headers['x-result-content-sha256'] !== item.content_sha256) throw new Error('material_version_changed')
    return response.data
  },
  judge: async (item: ResultSource, payload: { decision: JudgmentDecision; note: string; additional_sources: ResultSource[]; idempotency_key: string }) =>
    (await api.post<ResultMaterial>(`/results/${item.kind}/${encodeURIComponent(item.id)}/judgments`, { ...payload, content_sha256: item.content_sha256 })).data,
}
