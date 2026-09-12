import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from './api'
import { workbenchApi } from './workbench'

vi.mock('./api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

describe('日常工作台读取契约', () => {
  beforeEach(() => vi.clearAllMocks())

  it('分页只调用新只读接口，不启动会话或生成成果', async () => {
    const payload = { schema_version: 'daily-workbench-5.0-1' }
    vi.mocked(api.get).mockResolvedValue({ data: payload })
    expect(await workbenchApi.daily({ limit: 20, offset: 40 })).toBe(payload)
    expect(api.get).toHaveBeenCalledExactlyOnceWith('/workbench/daily', { params: { limit: 20, offset: 40 } })
    expect(api.post).not.toHaveBeenCalled()
  })

  it('读取失败继续抛出错误，不回退为旧流水线或空数据', async () => {
    const error = new Error('工作台接口不可用')
    vi.mocked(api.get).mockRejectedValue(error)
    await expect(workbenchApi.daily()).rejects.toBe(error)
    expect(api.get).toHaveBeenCalledExactlyOnceWith('/workbench/daily', { params: {} })
    expect(api.post).not.toHaveBeenCalled()
  })
})
