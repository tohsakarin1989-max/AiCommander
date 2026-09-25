import { describe, expect, it, vi } from 'vitest'
import { facilityAnalysisApi } from './facilityAnalysis'
import api from './api'
vi.mock('./api', () => ({ default: { get: vi.fn().mockResolvedValue({ data: {} }) } }))

describe('设施与区域只读接口', () => {
  it('设施读取只传稳定编号和原半开时间条件，并传取消信号', async () => {
    const signal = new AbortController().signal
    const params = { start_date: '2026-09-01T00:00:00Z', end_date: '2026-10-01T00:00:00Z' }
    await facilityAnalysisApi.dossier(8, params, signal)
    expect(api.get).toHaveBeenCalledWith('/facility-analysis/assets/8', { params, signal })
  })
  it('区域读取携带明确辖区和设施分页', async () => {
    const params = { operational_area_id: 2, page: 3, page_size: 20 }
    await facilityAnalysisApi.region(params)
    expect(api.get).toHaveBeenCalledWith('/facility-analysis/region', { params, signal: undefined })
  })
})
