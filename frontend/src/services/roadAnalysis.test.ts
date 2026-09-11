import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from './api'
import { compareCaseRoads, roadArtifactHistory, readRoadArtifact, readAutomaticRoadComparison, roadVehicleLabel, roadDetourLabel } from './roadAnalysis'

vi.mock('./api', () => ({ default: { post: vi.fn(), get: vi.fn() } }))
beforeEach(() => vi.resetAllMocks())
const fixture = () => ({ schema_version: 'case-road-comparison-4.2.0-1', result_id: 'frozen/result',
  content_sha256: 'hash', targets: [], information_gaps: ['缺少点位'], matrix: null })
describe('自动道路比较', () => {
  it('绕行说明采用道路端点，缺基准或过近时不显示失真倍数', () => {
    const reference = { basis: 'route_geometry_endpoints' as const, status: 'available' as const,
      straight_distance_m: 1000, road_distance_m: 2000, ratio: 2, additional_distance_m: 1000 }
    expect(roadDetourLabel(reference)).toContain('2.00 倍，多行 1.00 公里')
    expect(roadDetourLabel({ ...reference, status: 'endpoints_too_close', ratio: null })).toContain('不足 10 米')
    expect(roadDetourLabel({ ...reference, ratio: Infinity })).toContain('暂不显示')
    expect(roadDetourLabel()).toContain('未记录')
  })
  it('完成状态保留附件自身版本，缺少附件标识时拒绝下载依据', async () => {
    const signal = new AbortController().signal
    const artifact = { id: 'saved-road', content_sha256: 'a'.repeat(64), content: { ...fixture(), matrix: { cells: [] } } }
    const state = { result_id: 'frozen/result', content_sha256: 'hash', status: 'completed', artifact }
    vi.mocked(api.get).mockResolvedValue({ data: state })
    expect((await readAutomaticRoadComparison('frozen/result', 'hash', signal)).artifact).toEqual(artifact)
    for (const invalid of [{ ...artifact, id: '' }, { ...artifact, content_sha256: 'hash' }]) {
      vi.mocked(api.get).mockResolvedValue({ data: { ...state, artifact: invalid } })
      await expect(readAutomaticRoadComparison('frozen/result', 'hash', signal)).rejects.toThrow('内容不完整')
    }
  })
  it('明确标注车型来源和总重，不把缺失车型伪装成小客车事实', () => {
    expect(roadVehicleLabel({ kind: 'truck', source: 'case_record', height_m: 3.2, weight_t: 12.5 }))
      .toBe('货车（案件记录）；车高 3.2 米，总重 12.5 吨')
    expect(roadVehicleLabel({ kind: 'auto', source: 'explicit_reference_assumption' })).toContain('非案件事实')
    expect(roadVehicleLabel()).toContain('未记录车型')
  })
  it('页面查询使用GET，未完成状态不展示旧成果', async () => {
    const signal = new AbortController().signal
    const state = { result_id: 'frozen/result', content_sha256: 'hash', status: 'processing', artifact: null }
    vi.mocked(api.get).mockResolvedValue({ data: state })
    expect((await readAutomaticRoadComparison('frozen/result', 'hash', signal)).status).toBe('processing')
    expect(api.get).toHaveBeenCalledWith('/road-analysis/case-results/frozen%2Fresult/automatic-comparison', { signal })
    expect(api.post).not.toHaveBeenCalled()
    vi.mocked(api.get).mockResolvedValue({ data: { ...state, artifact: { content: fixture() } } })
    await expect(readAutomaticRoadComparison('frozen/result', 'hash', signal)).rejects.toThrow('未完成')
  })
  it('自动结果拒绝错误版本与不完整的完成状态', async () => {
    const signal = new AbortController().signal
    vi.mocked(api.get).mockResolvedValue({ data: { result_id: 'other', content_sha256: 'hash', status: 'completed' } })
    await expect(readAutomaticRoadComparison('frozen/result', 'hash', signal)).rejects.toThrow('版本不一致')
    vi.mocked(api.get).mockResolvedValue({ data: { result_id: 'frozen/result', content_sha256: 'hash', status: 'completed', artifact: null } })
    await expect(readAutomaticRoadComparison('frozen/result', 'hash', signal)).rejects.toThrow('内容不完整')
  })
  it('历史回看使用GET及固定版本，不重新发起计算', async () => {
    const signal = new AbortController().signal
    vi.mocked(api.get).mockResolvedValueOnce({ data: { items: [], next_before_id: null } })
    await roadArtifactHistory('frozen/result', signal, 'cursor')
    expect(api.get).toHaveBeenCalledWith('/road-analysis/case-results/frozen%2Fresult/artifacts', {
      params: { limit: 10, before_id: 'cursor' }, signal,
    })
    vi.mocked(api.get).mockResolvedValue({ data: { id: 'artifact', content_sha256: 'saved-hash', content: fixture() } })
    await readRoadArtifact('artifact', 'frozen/result', 'saved-hash', signal)
    await expect(readRoadArtifact('artifact', 'other-result', 'saved-hash', signal)).rejects.toThrow('引用不一致')
    expect(api.post).not.toHaveBeenCalled()
  })
  it('仅发送固定成果编号并传递取消信号，不要求用户选择设施', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: fixture() })
    const signal = new AbortController().signal
    expect((await compareCaseRoads('frozen/result', 'hash', signal)).matrix).toBeNull()
    expect(api.post).toHaveBeenCalledWith('/road-analysis/case-results/frozen%2Fresult/comparison', undefined, { signal })
  })
  it('拒绝把其他版本结果展示在当前案件上', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { ...fixture(), content_sha256: 'changed' } })
    await expect(compareCaseRoads('frozen/result', 'hash', new AbortController().signal)).rejects.toThrow('版本不一致')
  })
})
