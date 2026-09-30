import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'
import type { CaseTime, OilVolumeUnit } from '../types'
dayjs.extend(utc)
dayjs.extend(timezone)

export const oilUnitLabels: Record<OilVolumeUnit, string> = {
  tonne: '吨', liter: '升', kg: '千克', m3: '立方米', unknown: '单位未知',
}

export function formatStoredTime(value?: string | null, pattern = 'YYYY-MM-DD HH:mm', zone = 'Asia/Shanghai'): string {
  if (!value || !dayjs(value).isValid()) return '时间未明确'
  return dayjs(value).tz(zone).format(pattern)
}

export function formCaseTime(value?: string | null, zone = 'Asia/Shanghai') {
  return value && dayjs(value).isValid() ? dayjs(value).tz(zone) : null
}

/** Date controls express wall time in the selected record zone, not the browser zone. */
export function serializeCaseTime(value: unknown, zone = 'Asia/Shanghai'): unknown {
  if (dayjs.isDayjs(value)) return dayjs.tz(value.format('YYYY-MM-DD HH:mm:ss'), zone).toISOString()
  if (value && typeof value === 'object' && 'toISOString' in value && typeof value.toISOString === 'function') return value.toISOString()
  return value
}

export function formatCaseTime(value: CaseTime, pattern = 'YYYY-MM-DD HH:mm'): string {
  const precision = value.time_precision ?? (value.occurred_time ? 'exact' : 'unknown')
  if (precision === 'interval') return `${formatStoredTime(value.occurred_from, pattern, value.time_timezone || 'Asia/Shanghai')} 至 ${formatStoredTime(value.occurred_to, pattern, value.time_timezone || 'Asia/Shanghai')}（区间）`
  if (precision === 'unknown') return value.time_expression?.trim() ? `${value.time_expression}（时间未明确）` : '时间未明确'
  return formatStoredTime(value.occurred_time, pattern, value.time_timezone || 'Asia/Shanghai')
}

export function formatOilVolume(value?: number | null, unit?: OilVolumeUnit | null): string {
  return value == null || !Number.isFinite(value) ? '未记录' : `${value} ${oilUnitLabels[unit || 'unknown']}`
}
