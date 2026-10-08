import api from './api'

export interface PublicPlace { id: string; name: string; kind: string; latitude: number; longitude: number; location_role: string }
export interface PublicPlaceResult { items: PublicPlace[]; has_more: boolean; snapshot_id: string; snapshot_version: number; boundary: string }
export const mapPlacesApi = {
  search: async (snapshot: string, areaId: number, q: string, signal?: AbortSignal): Promise<PublicPlaceResult> =>
    (await api.get(`/maps/${encodeURIComponent(snapshot)}/places`, { params: { q, operational_area_id: areaId, limit: 50 }, signal })).data,
}

export function publicPlaceError(error: unknown): string {
  const value = error as { detail?: { detail?: { code?: string } }; response?: { data?: { detail?: { code?: string } } } }
  const code = value?.detail?.detail?.code ?? value?.response?.data?.detail?.code
  if (code === 'place_index_not_configured') return '当前地图版本未配置公共地名索引；设施目录仍可查找。'
  if (code === 'place_index_unavailable') return '公共地名索引暂不可用，请联系管理员；设施目录仍可查找。'
  return '公共地名查询失败或当前版本不可访问，不能视为没有地名。'
}
