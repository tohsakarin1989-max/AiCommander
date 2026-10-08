import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mapLedgerImportsApi } from './mapLedgerImports'
import { mapFoundationApi } from './mapFoundation'

const requests = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn() }))
vi.mock('./api', () => ({ default: requests }))

describe('生产台账接口契约', () => {
  beforeEach(() => { vi.clearAllMocks(); Object.values(requests).forEach(fn => fn.mockResolvedValue({ data: {} })) })
  it('字段字典/示例/受控原件分开读取，文件仍走权限接口', async () => {
    await mapLedgerImportsApi.fields(); await mapLedgerImportsApi.example(); await mapLedgerImportsApi.original('run/id')
    expect(requests.get.mock.calls).toEqual([
      ['/map-import-fields', { signal: undefined }], ['/map-import-example', { responseType: 'blob' }],
      ['/map-ingest-runs/run%2Fid/original', { responseType: 'blob' }],
    ])
  })
  it('批次和逐行来源均按服务端分页，异常筛选不在前端截取', async () => {
    const signal = new AbortController().signal
    await mapLedgerImportsApi.runs(6, 20, signal); await mapLedgerImportsApi.claims('a/b', 40, 'identity_pending', signal)
    expect(requests.get.mock.calls).toEqual([
      ['/map-ingest-runs', { params: { source_id: 6, offset: 20, limit: 10 }, signal }],
      ['/map-ingest-runs/a%2Fb/claims', { params: { offset: 40, limit: 20, classification: 'identity_pending' }, signal }],
    ])
  })
  it('预览文件与正式提交使用同一文件，plan_token 是明确表单字段', async () => {
    const file = new File(['井号\nA'], '台账.csv', { type: 'text/csv' })
    await mapLedgerImportsApi.preview(3, file, 9)
    const preview = requests.post.mock.calls[0]
    expect(preview[0]).toBe('/map-sources/3/preview'); expect(preview[1].get('file')).toBe(file)
    await mapFoundationApi.ingest(3, 9, file, '月度2', 'exact-plan-token')
    const ingest = requests.post.mock.calls[1]
    expect(ingest[0]).toBe('/map-sources/3/ingest')
    expect(ingest[1].get('file')).toBe(file); expect(ingest[1].get('plan_token')).toBe('exact-plan-token')
    expect(ingest[2].params).toEqual({ template_id: 9, source_revision: '月度2' })
  })
  it('预览修正不替换提交凭证，重试原样发送同请求', async () => {
    const frozen = { request_id: 'frozen-id', rows: [{ claim_id: 9, values: { 井号: 'A' } }], plan_token: 'plan' }
    await mapLedgerImportsApi.retryPreview('run', frozen); await mapLedgerImportsApi.retry('run', frozen); await mapLedgerImportsApi.retry('run', frozen)
    expect(requests.post.mock.calls).toEqual([
      ['/map-ingest-runs/run/retry-preview', frozen], ['/map-ingest-runs/run/retry', frozen], ['/map-ingest-runs/run/retry', frozen],
    ])
  })
  it('字段组裁决先读取当前采用状态，再带明确理由和版本令牌提交', async () => {
    await mapLedgerImportsApi.fieldDecisionPreview(7, 'water_cut')
    const request = { group: 'water_cut' as const, request_id: 'decision-fixed', note: '已核对量测口径', expected_asset_version: 4, expected_decision_id: null }
    await mapLedgerImportsApi.fieldDecision(7, request)
    expect(requests.get).toHaveBeenCalledWith('/map-conflicts/7/field-decision-preview', { params: { group: 'water_cut' }, signal: undefined })
    expect(requests.post).toHaveBeenCalledWith('/map-conflicts/7/field-decision', request)
  })
})
