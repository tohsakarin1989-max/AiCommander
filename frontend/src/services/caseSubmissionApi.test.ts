import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from './api'
import { caseApi } from './cases'
import type { CaseCreate } from '../types'
vi.mock('./api', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }))

describe('案件提交和来源翻页接口', () => {
  beforeEach(() => { vi.resetAllMocks(); vi.mocked(api.get).mockResolvedValue({ data: {} }); vi.mocked(api.post).mockResolvedValue({ data: { id: 12 } }) })
  it('POST携带稳定凭证，查询凭证编码，旧调用仍兼容', async () => {
    const payload = { description: '合成' } as CaseCreate
    await caseApi.createCase(payload, 'original-key')
    expect(api.post).toHaveBeenCalledWith('/cases', payload, { headers: { 'Idempotency-Key': 'original-key' } })
    await caseApi.getCaseSubmission('a:b')
    expect(api.get).toHaveBeenCalledWith('/cases/submissions/a%3Ab')
    await caseApi.createCase(payload)
    expect(api.post).toHaveBeenLastCalledWith('/cases', payload, undefined)
  })
  it('版本和原件使用独立游标，过滤先传给后端而非截取前20条', async () => {
    const signal = new AbortController().signal
    const params = { before_revision: 20, before_reference: 205, references_limit: 20, reference_kind: 'evidence' as const }
    await caseApi.getCaseSources(3, signal, params)
    expect(api.get).toHaveBeenCalledWith('/cases/3/sources', { signal, params })
  })
})
