import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Settings from './Settings'

const state = vi.hoisted(() => ({ enabled: false, unavailable: false, queries: [] as Array<{ queryKey: string[]; enabled?: boolean }> }))
vi.mock('../../config/useRuntimeFeatures', () => ({ useRuntimeFeatures: () => ({
  legacyOperationsEnabled: state.enabled,
  availability: { legacy_operations: state.unavailable ? 'unavailable' : state.enabled ? 'enabled' : 'disabled' },
  query: { refetch: vi.fn() },
}) }))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: (options: { queryKey: string[]; enabled?: boolean }) => {
    state.queries.push(options)
    return { data: [], isLoading: false }
  },
}))

describe('设置页历史模块能力边界', () => {
  beforeEach(() => { state.enabled = false; state.unavailable = false; state.queries = [] })

  it('关闭时既不显示历史管理页签，也不请求未挂载接口', () => {
    const html = renderToStaticMarkup(<Settings />)
    expect(html).not.toContain('保卫人员')
    expect(html).not.toContain('重要部位')
    for (const name of ['personnel', 'key-locations']) {
      expect(state.queries.find(query => query.queryKey[0] === name)?.enabled).toBe(false)
    }
  })

  it('明确开启后才显示页签并允许查询', () => {
    state.enabled = true
    const html = renderToStaticMarkup(<Settings />)
    expect(html).toContain('保卫人员')
    expect(html).toContain('重要部位')
    expect(state.queries.find(query => query.queryKey[0] === 'personnel')?.enabled).toBe(true)
  })

  it('读取失败说明未知状态，不误导为后台已关闭', () => {
    state.unavailable = true
    const html = renderToStaticMarkup(<Settings />)
    expect(html).toContain('历史模块状态暂不可用')
    expect(html).not.toContain('模块未启用')
    expect(state.queries.find(query => query.queryKey[0] === 'key-locations')?.enabled).toBe(false)
  })
})
