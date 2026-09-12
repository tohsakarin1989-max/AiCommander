import { isValidElement } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Assistant from './Assistant'
import { intelligentQueriesApi } from '../../services/intelligentQueries'
import type { QueryTask } from '../../services/intelligentQueries'

const state = vi.hoisted(() => ({
  params: new URLSearchParams(), question: '查看当前案件', hookIndex: 0,
  task: undefined as QueryTask | undefined, error: undefined as unknown,
  mutations: [] as Array<{ mutationFn: (...args: any[]) => unknown; onSuccess?: (...args: any[]) => unknown }>,
  submitted: [] as unknown[], queries: [] as Array<{ enabled: boolean }>,
}))
vi.mock('react', async original => {
  const actual = await original<typeof import('react')>()
  return { ...actual, useState: (value: unknown) => actual.useState(state.hookIndex++ === 0 ? state.question : value) }
})
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 1, role: 'analyst' }, sessionEpoch: 4 }) }))
vi.mock('react-router-dom', () => ({ useSearchParams: () => [state.params, vi.fn()] }))
vi.mock('../../services/intelligentQueries', async original => ({
  ...await original<typeof import('../../services/intelligentQueries')>(),
  intelligentQueriesApi: { create: vi.fn(), read: vi.fn(), cancel: vi.fn(), document: vi.fn() },
}))
vi.mock('@tanstack/react-query', () => ({
  useQuery: (options: typeof state.queries[number]) => {
    state.queries.push(options)
    return { data: state.task, error: state.error, isFetching: false, refetch: vi.fn() }
  },
  useMutation: (options: typeof state.mutations[number]) => {
    state.mutations.push(options)
    return { isPending: false, error: undefined, reset: vi.fn(), mutate: (args: unknown) => state.submitted.push(args) }
  },
}))

function visit(node: ReactNode, type: string): ReactElement<Record<string, any>> | undefined {
  if (Array.isArray(node)) return node.map(child => visit(child, type)).find(Boolean)
  if (!isValidElement<Record<string, any>>(node)) return undefined
  return node.type === type ? node : visit(node.props.children, type)
}

function render() {
  let tree: ReactNode
  function Capture() { tree = Assistant(); return tree }
  state.hookIndex = 0
  const html = renderToStaticMarkup(<Capture />)
  return { html, submit: () => visit(tree, 'form')!.props.onSubmit({ preventDefault: vi.fn() }) }
}

const id = '11111111-1111-4111-8111-111111111111'
const context = { schema_version: 'query-initial-context-5.0-1',
  source_case: { case_id: 42, operational_area_id: 1, source_hash: 'internal-source-version' },
  conditions: { case_filters: { case_id: 42, statuses: ['pending'] }, tool_defaults: {}, area: 1 } }

describe('助手继承案件选择', () => {
  beforeEach(() => {
    state.params = new URLSearchParams(); state.task = undefined; state.error = undefined
    state.question = '查看当前案件'; state.mutations = []; state.submitted = []; state.queries = []; vi.clearAllMocks()
  })

  it('展示初始条件但不自动创建，用户提交时才带入同一条件', async () => {
    state.params = new URLSearchParams('caseId=42&keyword=管线&has_geo=false')
    const page = render()
    expect(page.html).toContain('已带入当前案件与筛选条件')
    expect(page.html).toContain('案件编号：42')
    expect(page.html).toContain('有坐标：否')
    expect(page.html).toContain('不授予数据权限')
    expect(state.queries[0].enabled).toBe(false)
    expect(state.submitted).toEqual([])
    expect(intelligentQueriesApi.create).not.toHaveBeenCalled()
    page.submit()
    const submitted = state.submitted[0] as Record<string, unknown>
    expect(submitted.initialContext).toEqual({ source_case_id: 42, filters: { keyword: '管线', has_geo: false } })
    expect(submitted.parentId).toBeUndefined()
    await state.mutations[0].mutationFn(submitted)
    expect(intelligentQueriesApi.create).toHaveBeenCalledWith('查看当前案件', undefined, submitted.initialContext)
  })

  it('无效或混合 URL 上下文阻止提交，不退回全库', () => {
    for (const query of ['caseId=broken', `query=${id}&caseId=42`]) {
      state.params = new URLSearchParams(query)
      const page = render()
      expect(page.html).toContain('role="alert"')
      page.submit()
    }
    expect(state.submitted).toEqual([])
  })

  it('排队任务显示服务端冻结条件；源版本不显示为案情', () => {
    state.params = new URLSearchParams({ query: id })
    state.task = { id, query: '已提交问题', status: 'queued', result_kind: '', initial_context: context, result: {} }
    const { html } = render()
    expect(html).toContain('来源案件 ID：42')
    expect(html).toContain('案件编号：42')
    expect(html).toContain('排队中')
    expect(html).not.toContain('internal-source-version')
  })

  it('追问只提交 parent，不重新提交 URL 或客户端保存的案件版本', async () => {
    state.params = new URLSearchParams({ query: id })
    state.task = { id, query: '已提交问题', status: 'completed', result_kind: '', initial_context: context,
      result: { cards: [{ tool: 'count_cases', state: 'available', data: { count: 1 } }] } }
    const page = render()
    expect(page.html).toContain('继续追问')
    page.submit()
    const submitted = state.submitted[0] as Record<string, unknown>
    expect(submitted.parentId).toBe(id)
    expect(submitted.initialContext).toBeUndefined()
    await state.mutations[0].mutationFn(submitted)
    expect(intelligentQueriesApi.create).toHaveBeenCalledWith('查看当前案件', id, undefined)
  })

  it('读取失败隐藏缓存案件及结果，不用旧内容继续追问', () => {
    state.params = new URLSearchParams({ query: id })
    state.task = { id, query: '不再可见的问题', status: 'completed', result_kind: '', initial_context: context, result: {} }
    state.error = { response: { status: 403 } }
    const page = render()
    expect(page.html).not.toContain('不再可见的问题')
    expect(page.html).not.toContain('来源案件 ID：42')
    page.submit()
    expect(state.submitted).toEqual([])
  })
})
