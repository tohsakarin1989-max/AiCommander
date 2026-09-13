import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryObserver } from '@tanstack/react-query'
import api from './api'
import { caseWorkspaceApi, caseWorkspaceKey, visibleWorkspace, workspaceRefreshInterval } from './caseWorkspace'
import type { CaseWorkspace } from './caseWorkspace'

vi.mock('./api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
const fixture = (): CaseWorkspace => ({
  schema_version: 'case-workspace-5.0-1', case_id: 8, generated_at: '2026-09-12T01:00:00Z',
  case: { id: 8, case_number: '合成测试', status: 'pending', operational_area_id: 1 },
  pipeline: { status: 'completed', requested_at: null, completed_at: null },
  profile: { status: 'unavailable', data: null }, result: { status: 'unavailable', data: null },
  links: { case: '/cases?caseId=8', analysis: '/case-intelligence?caseId=8', map: '/cases/map?caseId=8',
    evidence: '/graphs/evidence?caseId=8', report: '/reports?caseId=8' }, boundary: '只读',
})

describe('案件工作界面共用读取', () => {
  beforeEach(() => vi.clearAllMocks())
  it('读取不触发生成，携带取消信号', async () => {
    const signal = new AbortController().signal
    const data = fixture()
    vi.mocked(api.get).mockResolvedValue({ data })
    expect(await caseWorkspaceApi.read(8, signal)).toBe(data)
    expect(api.get).toHaveBeenCalledExactlyOnceWith('/cases/8/workspace', { signal })
    expect(api.post).not.toHaveBeenCalled()
  })
  it('案件或结构不匹配时拒绝结果；失败不造空成果', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { ...fixture(), case_id: 9 } })
    await expect(caseWorkspaceApi.read(8)).rejects.toThrow('不一致')
    vi.mocked(api.get).mockRejectedValue(new Error('不可用'))
    await expect(caseWorkspaceApi.read(8)).rejects.toThrow('不可用')
    expect(api.post).not.toHaveBeenCalled()
  })
  it('同案共用缓存但不同用户、权限会话隔离；拒绝刷新后隐藏旧数据', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const key = caseWorkspaceKey(8, 1, 2)
    client.setQueryData(key, fixture())
    const observer = new QueryObserver<CaseWorkspace>(client, { queryKey: key,
      queryFn: async () => { throw new Error('撤权') }, enabled: false })
    expect(visibleWorkspace(observer.getCurrentResult(), 8)?.case_id).toBe(8)
    expect(visibleWorkspace(observer.getCurrentResult(), 9)).toBeUndefined()
    expect(visibleWorkspace(await observer.refetch(), 8)).toBeUndefined()
    expect(caseWorkspaceKey(8, 2, 2)).not.toEqual(key)
    expect(caseWorkspaceKey(8, 1, 3)).not.toEqual(key)
    await client.invalidateQueries({ queryKey: ['case-unified-result', 8] })
    expect(client.getQueryState(key)?.isInvalidated).toBe(true)
    observer.destroy()
    client.clear()
  })
  it('待更新轮询快于已稳定结果，缺数据不假装完成', () => {
    expect(workspaceRefreshInterval()).toBe(5000)
    expect(workspaceRefreshInterval(fixture())).toBe(30000)
    const data = fixture()
    data.result.status = 'updating'
    expect(workspaceRefreshInterval(data)).toBe(5000)
  })
})
