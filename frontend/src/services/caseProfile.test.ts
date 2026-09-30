import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from './api'
import { caseApi } from './cases'

vi.mock('./api', () => ({ default: { get: vi.fn() } }))

describe('案件资料聚合与历史检索分离', () => {
  beforeEach(() => vi.mocked(api.get).mockReset().mockResolvedValue({ data: {} }))
  it('日常工作界面可跳过旧版相似分析', async () => {
    await caseApi.getCaseProfile(42, { include_similar: false })
    expect(api.get).toHaveBeenCalledWith('/cases/42/profile', { params: { include_similar: false } })
  })
  it('其他既有调用不改变兼容默认', async () => {
    await caseApi.getCaseProfile(42)
    expect(api.get).toHaveBeenCalledWith('/cases/42/profile', { params: undefined })
  })
  it('兼容案件列表直接访问标准地址，避免代理跨端口重定向', async () => {
    await caseApi.getCases({ skip: 0, limit: 200 })
    expect(api.get).toHaveBeenCalledWith('/cases/', expect.objectContaining({
      params: expect.objectContaining({ skip: 0, limit: 200 }),
    }))
  })
})
