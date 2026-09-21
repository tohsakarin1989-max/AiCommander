import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Topics from './Topics'
import { TopicLinkedViews } from './TopicViews'
import { TopicForm } from './TopicForm'
import type { Topic, TopicViews } from '../../services/analysisTopics'
import { filterLines } from './topicPresentation'

const id = '11111111-1111-4111-8111-111111111111'
const state = vi.hoisted(() => ({ role: 'analyst', error: undefined as unknown, data: undefined as Topic | undefined,
  queries: [] as Array<{ queryKey: unknown[]; enabled?: boolean }> }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 1, role: state.role }, sessionEpoch: 1 }) }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: (options: { queryKey: unknown[]; enabled?: boolean }) => {
    state.queries.push(options)
    return { data: options.queryKey[0] === 'analysis-topic' ? state.data : undefined, error: state.error,
      isPending: false, isFetching: false, refetch: vi.fn() }
  },
  useMutation: () => ({ isPending: false, mutate: vi.fn(), error: undefined }),
}))
function renderPage(url = `/topics?topic=${id}&revision=1`) {
  return renderToStaticMarkup(<MemoryRouter initialEntries={[url]}><Topics /></MemoryRouter>)
}
const views: TopicViews = { snapshot_id: 'frozen', content_sha256: 'digest', boundary: '同版成果，不与背景材料相加',
  map: { points: [], versions: [], unmapped_in_page: 2 },
  graph: { groups: [{ category: 'tool', kind: 'negated', value: '软管', case_count: 91, case_ids: [8] }],
    case_ids: [8], boundary: '不是正式案件关系或实际轨迹' },
  timeline: [{ case_id: 8, occurred_time: null, profile_id: 'profile', profile_version: 1 }],
  case_results: [], roads: [], period_materials: [] }

describe('专题共享成果界面', () => {
  beforeEach(() => {
    state.role = 'analyst'; state.error = undefined; state.data = undefined; state.queries = []
  })
  it('读取失败时隐藏缓存成果和标题，不把故障显示为零', () => {
    state.data = { id, title: '不可再见的专题', notes: '', filters: {}, paused: false,
      refresh_state: 'ready', last_error: null, created_at: '', next_refresh_at: null }
    state.error = { status: 403 }
    const html = renderPage()
    expect(html).not.toContain('不可再见的专题')
    expect(html).toContain('权限或来源已变化')
    expect(html).not.toContain('独立事件 0')
  })
  it('查看用户和无效版本不能发起专题读取', () => {
    state.role = 'viewer'
    expect(renderPage()).toContain('无专题研判权限')
    expect(state.queries.every(query => !query.enabled)).toBe(true)
    state.role = 'analyst'; state.queries = []
    expect(renderPage(`/topics?topic=${id}&revision=oops`)).toContain('专题编号或版本无效')
    expect(state.queries.find(query => query.queryKey[0] === 'analysis-topic')?.enabled).toBe(false)
  })
  it('缺少历史底图时不使用当前地图，并保留无坐标计数', () => {
    const html = renderToStaticMarkup(<MemoryRouter><TopicLinkedViews views={views} tab="map" /></MemoryRouter>)
    expect(html).toContain('未使用当前底图代替历史版本')
    expect(html).toContain('本页无可用坐标：2')
    expect(html).toContain('/cases?caseId=8')
    expect(html).toContain('时间未提供')
  })
  it('案组保留否定、全组计数及正式关系边界', () => {
    const html = renderToStaticMarkup(<MemoryRouter><TopicLinkedViews views={views} tab="groups" /></MemoryRouter>)
    for (const word of ['原文否定', '全组 91 起', '不是正式案件关系', '/cases?caseId=8']) expect(html).toContain(word)
  })
  it('材料不存在不等同于无法通行或没有案件', () => {
    const html = renderToStaticMarkup(<MemoryRouter><TopicLinkedViews views={views} tab="materials" /></MemoryRouter>)
    expect(html).toContain('这不表示不可达')
    expect(html).toContain('未用专题统计冒充周期态势')
  })
  it('历史参考与本期统计分开，索引缺口不解释为无相关案件', () => {
    const withHistory: TopicViews = { ...views, history: { state: 'partial', boundary: '全部授权历史，不套用本期时间窗',
      selection: { conditions: [{ category: 'tool', value: '软管', kind: 'negated' }], available_condition_count: 1,
        condition_limit: 8, selection: 'saved_conditions' },
      result: { schema_version: 'case-history-5.1-1', source_case_id: null, state: 'partial',
        mode: 'lexical_fallback', semantic_index_state: 'not_enabled', items: [], boundary: '仅作参考',
        coverage: { authorized_cases: 105, scanned_cases: 105, matched_sources: 0,
          complete: false, scan_complete: true, missing_derived_sources: 7 } } } }
    const html = renderToStaticMarkup(<MemoryRouter><TopicLinkedViews views={withHistory} tab="materials" /></MemoryRouter>)
    for (const text of ['不计入本期统计', '原文否定', '105 起', '7 项来源缺少', '未重新抽取案情']) expect(html).toContain(text)
    expect(html).not.toContain('本次条件未找到匹配')
  })
  it('新专题不要求逐案选择，语义条件与否定分开呈现', () => {
    const html = renderToStaticMarkup(<TopicForm pending={false} onCreate={vi.fn()} />)
    expect(html).toContain('全部授权案件')
    expect(html).toContain('不需要逐案选择')
    expect(html).not.toContain('case_id')
    expect(filterLines({ conditions: [{ category: 'tool', value: '软管', kind: 'negated' }], has_geo: false }))
      .toEqual(['有坐标：false', '工具：软管（原文否定）'])
  })
})
