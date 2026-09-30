import { caseContextPath, parseCaseContextParams } from './caseContext'

export const regionalKeys = ['operational_area_id', 'start_date', 'end_date', 'assetId', 'eventId', 'caseId', 'time_scope', 'valid_at', 'known_at', 'mapSnapshot', 'resultRef'] as const
export type RegionalSelection = Partial<Record<typeof regionalKeys[number], string | number | null>>

/** Date controls use Beijing calendar dates without changing the shared exact instants. */
export function regionalCalendarDate(value?: string) {
  if (!value || !Number.isFinite(Date.parse(value))) return ''
  return new Date(Date.parse(value) + 8 * 60 * 60 * 1000).toISOString().slice(0, 10)
}

export function parseRegionalContext(params: URLSearchParams) {
  const { filters, caseId, error: caseError } = parseCaseContextParams(params)
  let error = caseError
  const readId = (key: string) => {
    const value = params.get(key)
    if (value == null) return null
    if (params.getAll(key).length !== 1 || !/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(Number(value))) {
      error = '设施、事件或辖区编号无效，未自动扩大范围。'
      return null
    }
    return Number(value)
  }
  const assetId = readId('assetId')
  const eventId = readId('eventId')
  const areaId = readId('operational_area_id')
  for (const key of ['start_date', 'end_date', 'caseId']) {
    if (params.getAll(key).length > 1) error = '选择条件重复，请修正后重试。'
  }
  const readInstant = (key: string) => {
    const value = params.get(key)
    if (value == null) return undefined
    const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/.exec(value)
    const calendar = match ? new Date(`${match[1]}T00:00:00Z`) : null
    const validCalendar = calendar != null && Number.isFinite(calendar.valueOf()) && calendar.toISOString().slice(0, 10) === match![1]
    if (params.getAll(key).length !== 1 || !match || !validCalendar || Number(match[2]) > 23 || Number(match[3]) > 59 || Number(match[4] || 0) > 59 || !Number.isFinite(Date.parse(value))) {
      error = '资料查询时刻无效，须明确时区；未回退为当前资料。'
      return undefined
    }
    return new Date(value).toISOString()
  }
  const validAt = readInstant('valid_at'), knownAt = readInstant('known_at')
  const readReference = (key: string) => {
    const value = params.get(key)
    if (value == null) return undefined
    if (params.getAll(key).length !== 1 || !/^[A-Za-z0-9_:.\-]{1,160}$/.test(value)) {
      error = '原成果引用格式无效，未替换为其他版本。'
      return undefined
    }
    return value
  }
  const mapSnapshot = readReference('mapSnapshot'), resultRef = readReference('resultRef')
  return { areaId, assetId, eventId, caseId, startDate: filters.start_date, endDate: filters.end_date, validAt, knownAt, mapSnapshot, resultRef, error }
}

export function writeRegionalContext(previous: URLSearchParams, changes: RegionalSelection) {
  const next = new URLSearchParams(previous)
  if ('operational_area_id' in changes && String(changes.operational_area_id ?? '') !== (previous.get('operational_area_id') ?? '')) {
    for (const key of ['assetId', 'eventId', 'caseId', 'facility_source_snapshot', 'mapSnapshot', 'resultRef']) next.delete(key)
  }
  for (const [key, value] of Object.entries(changes)) {
    next.delete(key)
    if (value != null && value !== '') next.set(key, String(value))
  }
  return next
}

export function regionalContextPath(target: string, source: URLSearchParams) {
  const value = caseContextPath(target, source)
  const [path, query] = value.split('?')
  const next = new URLSearchParams(query)
  for (const key of ['assetId', 'eventId', 'time_scope', 'valid_at', 'known_at', 'mapSnapshot', 'resultRef']) if (!next.has(key)) {
    for (const item of source.getAll(key)) next.append(key, item)
  }
  return `${path}${next.size ? `?${next}` : ''}`
}

export function openFacilityDossier(assetId: number, sourceSnapshot?: string) {
  if (!Number.isSafeInteger(assetId) || assetId <= 0) return
  window.dispatchEvent(new CustomEvent('aic:open-facility', { detail: { assetId, sourceSnapshot } }))
}

export function dossierSourcePath(target: string, params: URLSearchParams) {
  const source = writeRegionalContext(params, { assetId: null })
  source.delete('facility_source_snapshot')
  return regionalContextPath(target, source)
}
