import { beforeEach, describe, expect, it, vi } from 'vitest'
import { derivedOperations, type DerivedTask } from './derivedOperations'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('./api', () => ({ default: api }))

describe('管理员派生任务接口边界', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.get.mockResolvedValue({ data: { items: [] } })
    api.post.mockResolvedValue({ data: { accepted: true } })
  })
  it('列表限制页大小并携带筛选、取消信号', async () => {
    const signal = new AbortController().signal
    await derivedOperations.list(2, true, signal)
    expect(api.get).toHaveBeenCalledWith('/admin/derived-tasks', {
      params: { page: 2, page_size: 10, status: 'failed' }, signal,
    })
    await derivedOperations.list(1, false, signal)
    expect(api.get).toHaveBeenLastCalledWith('/admin/derived-tasks', {
      params: { page: 1, page_size: 10, status: undefined }, signal,
    })
  })
  it('重试仅传显式请求ID与预期尝试次数，不传任务载荷或案件事实', async () => {
    const signal = new AbortController().signal
    const row: DerivedTask = { id: 'task/1', kind: 'case.analysis.requested', label: '画像',
      status: 'failed', attempts: 3, created_at: '2026-10-05', available_at: '2026-10-05',
      retryable: true, source_state: 'current' }
    await derivedOperations.retry(row, 'request-1', signal)
    expect(api.post).toHaveBeenCalledWith('/admin/derived-tasks/task%2F1/retry',
      { request_id: 'request-1', expected_attempts: 3 }, { signal })
  })
})
