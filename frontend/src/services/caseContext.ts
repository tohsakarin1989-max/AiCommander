import type { CasePageParams } from './cases'

const filterKeys = ['keyword', 'statuses', 'case_types', 'oil_types', 'start_date', 'end_date', 'has_geo', 'operational_area_id'] as const
const positiveId = (value: string | null) => value && /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : null

export function parseCaseContextParams(params: URLSearchParams): { caseId: number | null; filters: CasePageParams; error?: string } {
  const caseId = positiveId(params.get('caseId'))
  const filters: CasePageParams = {}
  let error: string | undefined
  if (params.has('caseId') && !caseId) error = '案件编号无效，不能自动换成其他案件。'
  if (params.has('keyword')) filters.keyword = params.get('keyword')!
  for (const key of ['statuses', 'case_types', 'oil_types'] as const) {
    if (params.has(key)) filters[key] = params.getAll(key)
  }
  for (const key of ['start_date', 'end_date'] as const) {
    if (params.has(key)) {
      filters[key] = params.get(key)!
      if (!filters[key] || !Number.isFinite(Date.parse(filters[key]!))) error = '时间条件无效，请修改筛选。'
    }
  }
  if (filters.start_date && filters.end_date && Date.parse(filters.start_date) >= Date.parse(filters.end_date))
    error = '开始时间必须早于截止时间。'
  if (params.has('operational_area_id')) {
    const areaId = positiveId(params.get('operational_area_id'))
    if (areaId) filters.operational_area_id = areaId
    else error = '辖区参数无效，未自动扩大数据范围。'
  }
  if (params.has('has_geo')) {
    const value = params.get('has_geo')
    if (value === 'true' || value === 'false') filters.has_geo = value === 'true'
    else error = '坐标筛选参数无效，未自动取消筛选。'
  }
  return { caseId, filters, error }
}

export function writeCaseFilterParams(previous: URLSearchParams, filters: CasePageParams): URLSearchParams {
  const next = new URLSearchParams(previous)
  for (const key of filterKeys) {
    next.delete(key)
    const value = filters[key]
    if (Array.isArray(value)) for (const item of value) next.append(key, item)
    else if (value != null && value !== '') next.set(key, String(value))
  }
  return next
}

/** Stable internal links carry selection, never credentials, arbitrary URLs or report identities. */
export function caseContextPath(target: string, source: URLSearchParams): string {
  const [path, query = ''] = target.split('?')
  const next = new URLSearchParams(query)
  for (const key of [...filterKeys, 'caseId']) {
    if (!next.has(key)) for (const value of source.getAll(key)) next.append(key, value)
  }
  return `${path}${next.size ? `?${next}` : ''}`
}
