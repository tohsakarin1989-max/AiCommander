import type { ReactElement, ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DerivedOperationsPanel from './DerivedOperationsPanel'
import { derivedOperations, type DerivedTask } from '../../services/derivedOperations'

const state = vi.hoisted(() => ({
  auth: { user: { id: 1, role: 'admin' }, sessionEpoch: 1 },
  effects: [] as (() => void | (() => void))[], layouts: [] as (() => void | (() => void))[],
  refs: [] as { current: unknown }[], refCursor: 0,
  values: [] as unknown[], setters: [] as ReturnType<typeof vi.fn>[], stateCursor: 0,
  queryOptions: {} as Record<string, unknown>,
  query: { data: undefined as unknown, error: null as unknown, isFetching: false, isPending: false, refetch: vi.fn() },
}))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(),
  useRef: (initial: unknown) => state.refs[state.refCursor++] ?? (state.refs[state.refCursor - 1] = { current: initial }),
  useState: (initial: unknown) => {
    const index = state.stateCursor++
    if (!(index in state.values)) state.values[index] = initial
    state.setters[index] ??= vi.fn((value: unknown) => { state.values[index] = value })
    return [state.values[index], state.setters[index]]
  },
  useEffect: (effect: () => void | (() => void)) => state.effects.push(effect),
  useLayoutEffect: (effect: () => void | (() => void)) => state.layouts.push(effect),
}))
vi.mock('antd', () => ({ Alert: 'alert', Button: 'button', Checkbox: 'checkbox', Space: 'space', Table: 'table' }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => state.auth }))
vi.mock('../../services/derivedOperations', () => ({ derivedOperations: { list: vi.fn(), retry: vi.fn() } }))
vi.mock('@tanstack/react-query', () => ({ useQuery: (options: Record<string, unknown>) => {
  state.queryOptions = options
  return state.query
} }))

function find(node: ReactNode, type: string): ReactElement<Record<string, unknown>> | undefined {
  if (!node || typeof node !== 'object') return undefined
  if (Array.isArray(node)) return node.map(child => find(child, type)).find(Boolean)
  const value = node as ReactElement<Record<string, unknown>>
  return value.type === type ? value : find(value.props?.children as ReactNode, type)
}
const row: DerivedTask = { id: 'failed-1', kind: 'case.analysis.requested', label: '案件画像', status: 'failed',
  attempts: 3, created_at: '2026-10-05', available_at: '2026-10-05', retryable: true, source_state: 'current' }
function render() {
  state.refCursor = 0; state.stateCursor = 0
  return DerivedOperationsPanel()
}
function retry(tree: ReactNode) {
  const columns = find(tree, 'table')!.props.columns as { render?: (value: unknown, task: DerivedTask) => ReactElement<{ onClick: () => Promise<void> }> }[]
  return columns[4].render!(undefined, row).props.onClick()
}
function flushEffects() {
  state.layouts.splice(0).forEach(effect => effect())
  return state.effects.splice(0).map(effect => effect()).filter(Boolean) as (() => void)[]
}

describe('失败恢复面板权限与异步边界', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    state.auth = { user: { id: 1, role: 'admin' }, sessionEpoch: 1 }
    state.effects = []; state.layouts = []; state.refs = []; state.values = []; state.setters = []
    state.query = { data: { items: [row], counts: { failed: 1 }, total: 1, oldest_wait_seconds: null, boundary: '不改变原案件' },
      error: null, isFetching: false, isPending: false, refetch: vi.fn().mockResolvedValue({}) }
  })
  it('查询隔离账号和会话，非管理员不展示缓存列表', () => {
    render()
    expect(state.queryOptions.queryKey).toEqual(['derived-operations', 1, 1, 1, true])
    state.auth = { user: { id: 2, role: 'viewer' }, sessionEpoch: 2 }
    expect(render()).toBeNull()
    expect(state.queryOptions.enabled).toBe(false)
  })
  it('读取失败隐藏旧列表，不把缓存当作当前任务', () => {
    state.query.error = new Error('forbidden')
    const tree = render()
    expect(find(tree, 'table')!.props.dataSource).toEqual([])
    expect(find(tree, 'alert')!.props.message).toContain('已隐藏旧列表和数量')
  })
  it('丢失响应后再次点击复用请求ID，只有确认成功才刷新', async () => {
    vi.mocked(derivedOperations.retry).mockRejectedValueOnce(new Error('lost response')).mockResolvedValueOnce({ accepted: true })
    const tree = render(); flushEffects()
    await retry(tree)
    expect(state.query.refetch).not.toHaveBeenCalled()
    await retry(render())
    const calls = vi.mocked(derivedOperations.retry).mock.calls
    expect(calls[1][1]).toBe(calls[0][1])
    expect(state.query.refetch).toHaveBeenCalledOnce()
  })
  it('卸载后取消在途重试，迟到响应不刷新也不显示成功', async () => {
    let resolve: (value: unknown) => void = () => undefined
    vi.mocked(derivedOperations.retry).mockImplementation(() => new Promise(done => { resolve = done }))
    const tree = render(); const cleanups = flushEffects()
    const pending = retry(tree)
    cleanups.forEach(cleanup => cleanup())
    resolve({ accepted: true }); await pending
    expect(vi.mocked(derivedOperations.retry).mock.calls[0][2]?.aborted).toBe(true)
    expect(state.query.refetch).not.toHaveBeenCalled()
    expect(state.setters[3]).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }))
  })
  it('账号切换已渲染但被动effect未执行时，旧响应不得触发新会话提示或旧查询刷新', async () => {
    let resolve: (value: unknown) => void = () => undefined
    vi.mocked(derivedOperations.retry).mockImplementation(() => new Promise(done => { resolve = done }))
    const tree = render(); flushEffects()
    const pending = retry(tree)
    state.auth = { user: { id: 2, role: 'admin' }, sessionEpoch: 2 }
    render()
    // Commit-time layout cleanup can run before a promise; passive effects need
    // not have run yet. Do not grant old callbacks the new identity's authority.
    state.layouts.splice(0).forEach(effect => effect())
    resolve({ accepted: true }); await pending
    expect(state.query.refetch).not.toHaveBeenCalled()
    expect(state.setters[3]).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }))
  })
})
