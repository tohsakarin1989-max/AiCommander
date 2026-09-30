import type { CaseLocation } from '../../types'

export function caseLocationDraft(item: CaseLocation) {
  const coordinates = item.geometry?.coordinates
  return item.geometry?.type === 'Point' && Array.isArray(coordinates) && coordinates.length >= 2
    ? { ...item, ui_longitude: coordinates[0], ui_latitude: coordinates[1] }
    : item
}

export function locationCoordinateError(item: Record<string, unknown>): string | null {
  const lat = item.ui_latitude, lon = item.ui_longitude
  const hasLat = lat !== undefined && lat !== null, hasLon = lon !== undefined && lon !== null
  if (hasLat !== hasLon) return '经纬度须同时填写或同时清空'
  if (hasLat && (typeof lat !== 'number' || !Number.isFinite(lat) || lat < -90 || lat > 90)) return '纬度须在 -90 至 90 之间'
  if (hasLon && (typeof lon !== 'number' || !Number.isFinite(lon) || lon < -180 || lon > 180)) return '经度须在 -180 至 180 之间'
  if (item.precision === 'exact' && (!hasLat || !hasLon)) return '精确位置须填写已核对的经纬度；不明确时请选择未明确'
  return null
}
