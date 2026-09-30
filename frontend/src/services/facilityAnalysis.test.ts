import { describe, expect, it, vi } from 'vitest'
import { facilityAnalysisApi } from './facilityAnalysis'
import api from './api'
vi.mock('./api', () => ({ default: { get: vi.fn().mockResolvedValue({ data: {} }), post: vi.fn().mockResolvedValue({ data: {} }) } }))

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
  it('双时间独立于案件统计窗口，准备清单只发送授权范围与分页', async () => {
    const signal = new AbortController().signal
    const params = { valid_at: '2026-08-01T00:00:00Z', known_at: '2026-09-01T00:00:00Z', start_date: '2026-07-01T00:00:00Z' }
    await facilityAnalysisApi.dossier(8, params, signal)
    expect(api.get).toHaveBeenLastCalledWith('/facility-analysis/assets/8', { params, signal })
    await facilityAnalysisApi.readiness({ operational_area_id: 2, page: 3, page_size: 10 }, signal)
    expect(api.get).toHaveBeenLastCalledWith('/facility-analysis/readiness', { params: { operational_area_id: 2, page: 3, page_size: 10 }, signal })
  })
  it('关联和撤销按来源身份、前次决定和请求编号提交，不在服务中猜测名称或替换请求编号', async () => {
    const decision = { note: '台账核验', request_key: 'stable-request-key', previous_decision_id: 6 }
    await facilityAnalysisApi.bindIdentity(5, { ...decision, asset_id: 8 })
    expect(api.post).toHaveBeenLastCalledWith('/facility-analysis/identities/5/bind', { ...decision, asset_id: 8 })
    await facilityAnalysisApi.revokeIdentity(5, decision)
    expect(api.post).toHaveBeenLastCalledWith('/facility-analysis/identities/5/revoke', decision)
  })
  it('人工材料关联绑定当前案件修订与选定引用，撤销不使用案件或设施编号替代关联编号', async () => {
    const payload = { case_id: 8, source_reference_id: 32, source_revision_id: 24, relation_type: 'mentioned' as const, note: '原文提及此设施', request_key: 'stable-material-key' }
    await facilityAnalysisApi.createCaseLink(5, payload)
    expect(api.post).toHaveBeenLastCalledWith('/facility-analysis/assets/5/case-links', payload)
    await facilityAnalysisApi.revokeCaseLink(11, '材料关系录入有误')
    expect(api.post).toHaveBeenLastCalledWith('/facility-analysis/case-links/11/revoke', { note: '材料关系录入有误' })
  })
})
