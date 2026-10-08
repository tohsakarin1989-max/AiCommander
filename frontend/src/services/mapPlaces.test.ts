import { describe, expect, it, vi } from 'vitest'
import { mapPlacesApi, publicPlaceError } from './mapPlaces'
const get = vi.hoisted(() => vi.fn().mockResolvedValue({ data: { items: [] } }))
vi.mock('./api', () => ({ default: { get } }))
describe('公共地名沿用授权冻结版本接口', () => {
  it('不查询生产设施或current，传取消信号和明确辖区', async () => {
    const signal = new AbortController().signal
    await mapPlacesApi.search('snapshot-1', 7, '合成村', signal)
    expect(get).toHaveBeenCalledWith('/maps/snapshot-1/places', { params: { q: '合成村', operational_area_id: 7, limit: 50 }, signal })
  })
  it('缺索引与读取失败分别说明，不能把失败当成空结果', () => {
    expect(publicPlaceError({ detail: { detail: { code: 'place_index_not_configured' } } })).toContain('未配置')
    expect(publicPlaceError({ detail: { detail: { code: 'place_index_unavailable' } } })).toContain('暂不可用')
    expect(publicPlaceError(new Error('403'))).toContain('不能视为没有地名')
  })
})
