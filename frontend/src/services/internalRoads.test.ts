import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from './api'
import { internalRoadsApi, type RoadFeature, type RoadImport } from './internalRoads'

vi.mock('./api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
beforeEach(() => vi.resetAllMocks())

describe('内部道路接口契约', () => {
  it('设施归属必须显式确认，不随道路连接默认批准', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} })
    const record = { id: 3, input_sha256: 'a'.repeat(64), entrance_checks: [{ entrance_id: 'entry',
      road_import_id: 2, road_source_sha256: 'b'.repeat(64) }] } as RoadImport
    const feature = { id: 'entry', properties: { kind: 'entrance', facility_asset_id: 13 } } as RoadFeature
    await internalRoadsApi.review(1, record, feature, 'verified', '核验', '依据', 'connected')
    expect(vi.mocked(api.post).mock.calls[0][1]).not.toHaveProperty('connection_evidence.facility_asset_id')
    await internalRoadsApi.review(1, record, feature, 'verified', '核验', '依据', 'connected', undefined, true)
    expect(vi.mocked(api.post).mock.calls[1][1]).toHaveProperty('connection_evidence.facility_asset_id', 13)
    await expect(internalRoadsApi.review(1, record, feature, 'verified', '核验', '依据', 'unknown', undefined, true)).rejects.toThrow()
    expect(api.post).toHaveBeenCalledTimes(2)
  })
  it('新增道路连接只随已核验道路提交，保留固定批次与前次决定', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} })
    const record = { id: 3, input_sha256: 'a'.repeat(64), feature_reviews: { r: { id: 2 } } } as unknown as RoadImport
    const feature = { id: 'r', properties: { kind: 'road' } } as RoadFeature
    const geometry = { kind: 'new_road' as const, public_source_sha256: 'b'.repeat(64),
      connections: [{ component: 0, endpoint: 'start' as const, osm_node_id: 12345 }] }
    await internalRoadsApi.review(1, record, feature, 'verified', '说明', '依据', undefined, geometry)
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ previous_review_id: 2,
      input_sha256: record.input_sha256, connection_evidence: geometry })
    await expect(internalRoadsApi.review(1, record, feature, 'rejected', '说明', '依据', undefined, geometry)).rejects.toThrow()
    expect(api.post).toHaveBeenCalledTimes(1)
  })
  it('公共道路关联绑定双端版本并保留请求标识', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [] } })
    vi.mocked(api.post).mockResolvedValue({ data: {} })
    const signal = new AbortController().signal
    await internalRoadsApi.publicAliases(3, 17, '路:1', 'a'.repeat(64), 8, signal)
    expect(api.get).toHaveBeenCalledWith('/map-sources/3/roads/imports/17/features/%E8%B7%AF%3A1/public-aliases', {
      params: { public_source_sha256: 'a'.repeat(64), before_id: 8, limit: 20 }, signal,
    })
    const payload = { import_id: 17, feature_id: '路:1', public_source_sha256: 'a'.repeat(64),
      osm_way_id: 12345678901, decision: 'verified' as const, request_key: 'same-request',
      evidence_reference: '合成核验', previous_id: null }
    await internalRoadsApi.recordPublicAlias(3, payload)
    expect(api.post).toHaveBeenCalledWith('/map-sources/3/roads/public-aliases', payload)
    await expect(internalRoadsApi.recordPublicAlias(3, { ...payload, osm_way_id: Number.MAX_SAFE_INTEGER + 1 })).rejects.toThrow()
    expect(api.post).toHaveBeenCalledTimes(1)
  })
  it('入口连接证据绑定后端返回的道路版本，缺失版本不得提交', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} })
    const record = { id: 3, input_sha256: 'a'.repeat(64), entrance_checks: [{ entrance_id: 'entry',
      road_import_id: 2, road_source_sha256: 'b'.repeat(64) }] } as RoadImport
    const feature = { id: 'entry' } as RoadFeature
    await internalRoadsApi.review(1, record, feature, 'verified', '核对记录', '合成依据', 'connected')
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ connection_evidence: {
      road_import_id: 2, road_source_sha256: 'b'.repeat(64), status: 'connected',
    } })
    await expect(internalRoadsApi.review(1, record, feature, 'pending_verification', '备注', '依据', 'connected')).rejects.toThrow()
    await expect(internalRoadsApi.review(1, { ...record, entrance_checks: [] }, feature, 'verified', '备注', '依据', 'connected')).rejects.toThrow()
    expect(api.post).toHaveBeenCalledTimes(1)
  })
  it('目录按来源编号游标查询并传递取消信号', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: {} })
    const signal = new AbortController().signal
    await internalRoadsApi.catalog(3, 'road-17', signal)
    expect(api.get).toHaveBeenCalledWith('/map-sources/3/roads/catalog', {
      params: { after_feature: 'road-17', limit: 20 }, signal,
    })
  })
  it('比较固定来源与两个版本，不请求current或省略授权来源', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: {} })
    const signal = new AbortController().signal
    await internalRoadsApi.compare(3, 17, 18, signal)
    expect(api.get).toHaveBeenCalledWith('/map-sources/3/roads/compare', {
      params: { before_id: 17, after_id: 18 }, signal,
    })
  })
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
