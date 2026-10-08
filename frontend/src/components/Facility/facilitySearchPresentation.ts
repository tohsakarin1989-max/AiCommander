import type { JurisdictionAsset } from '../../services/jurisdiction'

export function facilityMatchText(asset: JurisdictionAsset): string | null {
  const match = asset.search_match
  if (!match) return null
  const labels = { current_name: '当前名称', external_id: '台账编号', address: '登记地址', historical_name: '历史名称匹配（不是当前名称）', source_alias: '来源别名匹配（不是当前名称）' }
  return `${labels[match.kind] || '匹配线索'}：${match.value}`
}

export function facilityPoint(asset: Pick<JurisdictionAsset, 'latitude' | 'longitude'>): [number, number] | null {
  const { latitude, longitude } = asset
  return typeof latitude === 'number' && Number.isFinite(latitude) && Math.abs(latitude) <= 90
    && typeof longitude === 'number' && Number.isFinite(longitude) && Math.abs(longitude) <= 180 ? [latitude, longitude] : null
}
