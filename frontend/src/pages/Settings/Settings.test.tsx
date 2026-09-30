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

describe('设置页旧模块退出边界', () => {
  beforeEach(() => { state.enabled = false; state.unavailable = false; state.queries = [] })

  it('关闭时既不显示历史管理页签，也不请求未挂载接口', () => {
    const html = renderToStaticMarkup(<Settings />)
    expect(html).not.toContain('保卫人员')
    expect(html).not.toContain('重要部位')
    for (const name of ['personnel', 'key-locations']) {
      expect(state.queries.find(query => query.queryKey[0] === name)).toBeUndefined()
    }
  })

  it('旧功能标记不能重新显示或请求退出的模块', () => {
    state.enabled = true
    const html = renderToStaticMarkup(<Settings />)
    expect(html).not.toContain('保卫人员')
    expect(html).not.toContain('重要部位')
    expect(state.queries.map(query => query.queryKey[0])).toEqual(['configs', 'configs', 'models'])
    expect(html).toContain('AI 模型')
    expect(state.queries.map(query => query.queryKey)).toEqual([['configs', 'map'], ['configs', 'meeting'], ['models']])
  })

  it('旧标记读取失败不再显示无法恢复的功能提示', () => {
    state.unavailable = true
    const html = renderToStaticMarkup(<Settings />)
    expect(html).not.toContain('历史模块状态暂不可用')
    expect(html).not.toContain('模块未启用')
    expect(state.queries.find(query => query.queryKey[0] === 'key-locations')).toBeUndefined()
  })
})
