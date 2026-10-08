import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from './api'
import { readAutomaticRoadComparison, type FacilityComparisonProgress } from './roadAnalysis'

vi.mock('./api', () => ({ default: { get: vi.fn() } }))
const progress = (): FacilityComparisonProgress => ({ phase: 'roads', scanned: 120, scan_complete: true,
  candidate_pool_size: 100, candidate_pool_limit: 100, entrance_facilities_checked: 100,
  entrance_facilities_total: 100, entrance_check_complete: true, road_targets_completed: 10,
  road_targets_total: 200, road_complete: false, dependency_policy: 'whole_authorized_scope_conservative',
  boundary: '候选池有上限，不宣称全域最优。' })
const response = (value?: FacilityComparisonProgress) => ({ result_id: 'frozen', content_sha256: 'hash',
  status: 'processing', artifact: null, ...(value ? { progress: value } : {}) })
const read = () => readAutomaticRoadComparison('frozen', 'hash', new AbortController().signal)

describe('道路续跑进度契约', () => {
  beforeEach(() => vi.resetAllMocks())
  it('接收实际计数，允许扫描多于池上限及道路总数未知，不补百分比', async () => {
    for (const value of [progress(), { ...progress(), road_targets_completed: 0, road_targets_total: null }]) {
      vi.mocked(api.get).mockResolvedValue({ data: response(value) })
      expect((await read()).progress).toEqual(value)
    }
    vi.mocked(api.get).mockResolvedValue({ data: response() })
    expect((await read()).progress).toBeUndefined()
  })
  it.each([
    { scanned: -1 }, { scanned: 1.5 }, { candidate_pool_size: 101 }, { candidate_pool_limit: 200 },
    { entrance_facilities_checked: 101 }, { road_targets_completed: 201 },
    { road_targets_total: null, road_complete: true }, { phase: 'done' },
    { dependency_policy: 'unbounded' }, { boundary: '' },
  ])('拒绝不完整或矛盾进度：%j', async patch => {
    vi.mocked(api.get).mockResolvedValue({ data: response({ ...progress(), ...patch } as FacilityComparisonProgress) })
    await expect(read()).rejects.toThrow('版本不一致')
  })
  it('不可用状态只接受明确原因，不能夹带旧进度', async () => {
    for (const reason of ['frozen_inputs_unavailable', 'frozen_inputs_changed']) {
      const state = { ...response(), status: 'unavailable', reason }
      vi.mocked(api.get).mockResolvedValue({ data: state })
      expect((await read()).reason).toBe(reason)
      vi.mocked(api.get).mockResolvedValue({ data: { ...state, progress: progress() } })
      await expect(read()).rejects.toThrow('版本不一致')
    }
  })
})
