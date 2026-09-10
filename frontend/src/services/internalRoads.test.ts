import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from './api'
import { internalRoadsApi, type RoadFeature, type RoadImport } from './internalRoads'

vi.mock('./api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
beforeEach(() => vi.resetAllMocks())

describe('内部道路接口契约', () => {
  it('列表和历史读取固定来源及批次，并传递取消信号', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { id: 17 } })
    const signal = new AbortController().signal
    await internalRoadsApi.list(3, 40, signal)
    expect(api.get).toHaveBeenCalledWith('/map-sources/3/roads/imports', { params: { before_id: 40, limit: 20 }, signal })
    await internalRoadsApi.read(3, 17, signal)
    expect(api.get).toHaveBeenLastCalledWith('/map-sources/3/roads/imports/17', { signal })
  })
  it('预检与保存不转换线形，不改为点位导入接口', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { valid: 1 } })
    const payload = { type: 'FeatureCollection', coordinate_system: 'EPSG:4326', features: [] }
    await internalRoadsApi.preview(3, payload)
    expect(api.post).toHaveBeenLastCalledWith('/map-sources/3/roads/preview', payload)
    await internalRoadsApi.ingest(3, payload)
    expect(api.post).toHaveBeenLastCalledWith('/map-sources/3/roads/ingest', payload)
  })
  it('核验提交固定摘要与前次决定，不携带通行授权或改写几何', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { id: 10 } })
    const record = { id: 17, input_sha256: 'a'.repeat(64), feature_reviews: { '路:1': { id: 9 } } } as unknown as RoadImport
    const feature = { id: '路:1' } as RoadFeature
    await internalRoadsApi.review(3, record, feature, 'verified', '依据已核对', '台账')
    const [path, data] = vi.mocked(api.post).mock.calls[0]
    expect(path).toBe('/map-sources/3/roads/imports/17/features/%E8%B7%AF%3A1/reviews')
    expect(data).toEqual({ input_sha256: 'a'.repeat(64), request_key: expect.any(String), previous_review_id: 9,
      decision: 'verified', note: '依据已核对', evidence_reference: '台账' })
  })
  it('失败不自动重试或回退到其他来源', async () => {
    vi.mocked(api.post).mockRejectedValue(new Error('permission denied'))
    await expect(internalRoadsApi.ingest(3, {})).rejects.toThrow('permission denied')
    expect(api.post).toHaveBeenCalledTimes(1)
  })
})
