import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ContinuationResult, continuationPollInterval } from './ContinuationResult'
import { QueryResult } from './QueryResult'
import type { AggregateContinuation } from '../../services/intelligentQueries'

const id = '11111111-1111-4111-8111-111111111111'
const otherId = '22222222-2222-4222-8222-222222222222'
type QueryOptions = { queryKey: unknown[]; enabled: boolean; retry: boolean; refetchOnMount: string;
  queryFn: (context: { signal: AbortSignal }) => Promise<unknown>;
  refetchInterval: (query: { state: { data?: AggregateContinuation; error?: unknown } }) => number | false }
type MutationOptions = { mutationFn: (args: { jobId: string; identity: string }) => Promise<unknown>;
  onSuccess: (response: unknown, args: { jobId: string; identity: string }) => Promise<void> }
const state = vi.hoisted(() => ({ userId: 7, session: 2, role: 'analyst', data: undefined as AggregateContinuation | undefined,
  error: undefined as unknown, mutationError: undefined as unknown, fetched: true,
  queries: [] as QueryOptions[], mutation: undefined as MutationOptions | undefined,
  refetch: vi.fn(), get: vi.fn(), post: vi.fn() }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: state.userId, role: state.role }, sessionEpoch: state.session }) }))
vi.mock('../../services/api', () => ({ default: { get: state.get, post: state.post } }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: (options: QueryOptions) => {
    state.queries.push(options)
    return { data: state.data, error: state.error, isFetchedAfterMount: state.fetched, isFetching: false, refetch: state.refetch }
  },
  useMutation: (options: MutationOptions) => {
    state.mutation = options
    return { isPending: false, error: state.mutationError, mutate: vi.fn(), reset: vi.fn() }
  },
}))
const partial = { schema_version: 'profile-aggregate-5.3-1', coverage: { complete: false, scanned_cases: 12, authorized_cases: 350 },
  statistics: { denominator: 12, matched: 4, unmatched: 3, unknown: 5 }, boundary: '仅部分案例依据' }
const job: AggregateContinuation = { id, status: 'processing', progress: { phase: 'cases', scanned_cases: 120, total_cases: 350 },
  as_of: '2026-09-30T08:00:00Z', scope_version: 'scope-frozen' }
function render(continuation = job) {
  return renderToStaticMarkup(<MemoryRouter><ContinuationResult continuation={continuation} partial={partial} /></MemoryRouter>)
}
describe('助手后台统计续跑', () => {
  beforeEach(() => {
    state.userId = 7; state.session = 2; state.role = 'analyst'; state.data = job
    state.error = undefined; state.mutationError = undefined; state.fetched = true; state.queries = []
    state.refetch.mockReset(); state.get.mockReset(); state.post.mockReset()
  })
  it('展示实际分块进度，保留交互部分统计且允许刷新和取消', () => {
    const html = render()
    for (const text of ['120 / 350', '正在分批统计', '遍历案件', '2026-09-30T08:00:00Z', '刷新后台进度', '取消后台统计',
      '尚未遍历全部范围', '不是后台最终结果', '自动更新最多 3 分钟']) expect(html).toContain(text)
    expect(html).not.toContain('后台完成统计')
  })
  it('只读取完成任务的新结果，不把交互部分数据混作最终结果', () => {
    state.data = { ...job, status: 'completed', result: { ...partial,
      coverage: { complete: true, scanned_cases: 350, authorized_cases: 350 }, statistics: { denominator: 350, matched: 80 }, boundary: '完整数据依据' } }
    const html = render()
    expect(html).toContain('已遍历全部授权候选范围')
    expect(html).toContain('完整数据依据')
    expect(html).not.toContain('仅部分案例依据')
    expect(html).not.toContain('取消后台统计')
  })
  it.each([401, 403, 404, 500])('读取失败 %s 后隐藏缓存完整结果、部分统计和数量', status => {
    state.data = { ...job, status: 'completed', result: { ...partial, boundary: '不得展示的旧结果' } }
    state.error = { response: { status } }
    const html = render()
    for (const text of ['不得展示的旧结果', '仅部分案例依据', '120 / 350']) expect(html).not.toContain(text)
    expect(html).toContain(status === 500 ? '旧内容已隐藏' : '不能继续显示旧统计')
  })
  it('取消请求遇到授权失败也隐藏缓存内容', () => {
    state.mutationError = { response: { status: 403 } }
    expect(render()).not.toContain('仅部分案例依据')
    expect(render()).toContain('不能继续显示旧统计')
  })
  it('切换任务后不得显示前任务，缓存未经本次核验不展示', () => {
    let html = render({ ...job, id: otherId })
    expect(html).toContain('正在核验当前任务')
    expect(html).not.toContain('120 / 350')
    expect(state.queries[state.queries.length - 1]?.queryKey).toEqual(['query-aggregate-continuation', 7, 2, otherId])
    state.fetched = false
    html = render()
    expect(html).not.toContain('仅部分案例依据')
    state.userId = 8; state.session = 3; render()
    expect(state.queries[state.queries.length - 1]?.queryKey).toEqual(['query-aggregate-continuation', 8, 3, id])
  })
  it('读取固定接口并传递取消信号，取消仅操作现有任务', async () => {
    render()
    state.get.mockResolvedValue({ data: job }); state.post.mockResolvedValue({ data: { ...job, status: 'cancelled' } })
    const signal = new AbortController().signal
    await state.queries[0].queryFn({ signal })
    expect(state.get).toHaveBeenCalledWith(`/analysis-topics/aggregations/${id}`, { signal })
    await state.mutation?.mutationFn({ jobId: id, identity: `7:2:${id}` })
    expect(state.post).toHaveBeenCalledExactlyOnceWith(`/analysis-topics/aggregations/${id}/cancel`)
    await state.mutation?.onSuccess({}, { jobId: otherId, identity: `7:2:${otherId}` })
    expect(state.refetch).not.toHaveBeenCalled()
    await state.mutation?.onSuccess({}, { jobId: id, identity: `7:2:${id}` })
    expect(state.refetch).toHaveBeenCalledExactlyOnceWith()
  })
  it('有界轮询只跟踪活动任务，遇错和结束时停止', () => {
    expect(continuationPollInterval('pending', 0, null)).toBe(3000)
    expect(continuationPollInterval('retry', 179_999, null)).toBe(3000)
    expect(continuationPollInterval('processing', 180_000, null)).toBe(false)
    for (const status of ['completed', 'cancelled', 'superseded', 'failed', undefined])
      expect(continuationPollInterval(status, 0, null)).toBe(false)
    expect(continuationPollInterval('processing', 0, new Error('offline'))).toBe(false)
  })
  it.each(['superseded', 'cancelled', 'failed'] as const)('终止状态 %s 不再显示部分统计或自动重启', status => {
    state.data = { ...job, status }
    const html = render()
    expect(html).not.toContain('仅部分案例依据')
    expect(html).not.toContain('取消后台统计')
    expect(state.post).not.toHaveBeenCalled()
  })
  it('无效编号和只读用户不发读取请求', () => {
    render({ ...job, id: 'https://invalid.example/anything' })
    expect(state.queries[state.queries.length - 1]?.enabled).toBe(false)
    state.role = 'viewer'
    expect(render()).toContain('当前账号不能读取后台统计')
    expect(state.queries[state.queries.length - 1]?.enabled).toBe(false)
  })
  it('无续跑容量时保留真实部分状态，不编造任务或完成结果', () => {
    const html = renderToStaticMarkup(<ContinuationResult continuation={{ status: 'unavailable' }} partial={partial} />)
    expect(html).toContain('本次未创建续跑任务')
    expect(html).toContain('尚未遍历全部范围')
    expect(state.queries).toHaveLength(0)
  })
  it('QueryResult确实接入续跑，失权时卡片旧来源和缺口也不泄漏', () => {
    state.error = { response: { status: 403 } }
    const html = renderToStaticMarkup(<QueryResult card={{ tool: 'aggregate_case_profiles', state: 'partial', data: partial,
      continuation: job, information_gaps: ['过期缺口'], evidence: { filters: { keyword: '过期资料' } } }} />)
    expect(html).toContain('不能继续显示旧统计')
    expect(html).not.toContain('过期缺口')
    expect(html).not.toContain('过期资料')
  })
})
