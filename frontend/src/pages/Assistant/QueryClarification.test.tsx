import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QueryClarification from './QueryClarification'
import type { QueryTask } from '../../services/intelligentQueries'

const state = vi.hoisted(() => ({ choose: undefined as undefined | ((item: { id: number }) => void),
  submits: [] as unknown[], queries: [] as { enabled: boolean }[], error: false }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 1 }, sessionEpoch: 2 }) }))
vi.mock('../../components/CaseSearch', () => ({ default: (props: { onChoose: (item: { id: number }) => void; disabled: boolean }) => {
  state.choose = props.onChoose; return <span>{props.disabled ? '选择不可用' : '选择一条记录'}</span>
} }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: (options: { enabled: boolean }) => { state.queries.push(options); return {
    isError: state.error, data: [{ id: 9, status: 'active', name: '不可泄露旧缓存' }], refetch: vi.fn() } },
  useMutation: () => ({ isPending: false, error: null, mutate: (payload: unknown) => state.submits.push(payload) }),
}))
const task = { id: 'one', status: 'waiting_clarification', source_context: { area_id: 1 },
  clarification: { id: 'clarify-one', field: 'case_id', prompt: '要查看哪条记录？', expires_at: '2099-01-01T00:00:00Z' } } as QueryTask

describe('只补一个必要条件', () => {
  beforeEach(() => { state.choose = undefined; state.submits = []; state.queries = []; state.error = false })
  it('等待不启动查询；选择后幂等重试不更换原值', () => {
    renderToStaticMarkup(<QueryClarification task={task} enabled onUpdated={vi.fn()} />)
    expect(state.submits).toEqual([])
    expect(state.queries[0].enabled).toBe(false)
    state.choose!({ id: 3 }); state.choose!({ id: 4 })
    expect(state.submits[0]).toMatchObject({ clarification_id: 'clarify-one', value: 3 })
    expect(state.submits[1]).toEqual(state.submits[0])
  })
  it('区域权限失败不展示旧缓存', () => {
    state.error = true
    const html = renderToStaticMarkup(<QueryClarification task={{ ...task, clarification: { ...task.clarification!, field: 'area_id' } }} enabled onUpdated={vi.fn()} />)
    expect(html).toContain('区域列表读取失败')
    expect(html).not.toContain('不可泄露旧缓存')
    expect(state.submits).toEqual([])
  })
  it('到期和功能停用均不发起续跑', () => {
    const expired = renderToStaticMarkup(<QueryClarification task={{ ...task,
      clarification: { ...task.clarification!, expires_at: '2000-01-01T00:00:00Z' } }} enabled onUpdated={vi.fn()} />)
    expect(expired).toContain('已到期')
    renderToStaticMarkup(<QueryClarification task={task} enabled={false} onUpdated={vi.fn()} />)
    state.choose!({ id: 3 })
    expect(state.submits).toEqual([])
  })
})
