import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DailyReviewPreview from './DailyReviewPreview'
import { suggestionsApi, type SuggestionsResponse } from '../../services/suggestions'

const state = vi.hoisted(() => ({ loading: false, failed: false, empty: false, epoch: 2, role: 'analyst',
  queries: [] as Array<{ queryKey: unknown[]; queryFn: () => unknown }>,
}))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 7, role: state.role }, sessionEpoch: state.epoch }) }))
vi.mock('react-router-dom', () => ({ Link: ({ children, to }: { children: ReactNode; to: string }) => <a href={to}>{children}</a> }))
vi.mock('../../services/suggestions', () => ({ suggestionsApi: { list: vi.fn() } }))
vi.mock('@tanstack/react-query', () => ({ useQuery: (query: typeof state.queries[number]) => {
  state.queries.push(query)
  const data: SuggestionsResponse = {
    suggestions: state.empty ? [] : [1, 2, 3, 4].map(id => ({
      id: `conclusion-review-${id}`, title: `已有结论-${id}`, description: `结论 ${id} 的事实与推断需人工判断`,
      type: 'review', priority: 'medium', workflow: 'conclusion_review', action: 'review_conclusion',
      target_type: 'conclusion', target_id: `source/${id}`, status: 'open', created_at: '2026-09-12T00:00:00Z',
    })),
    total: state.empty ? 0 : 8, generated_at: '2026-09-12T08:00:00Z',
    summary: { total: 99, priority: { high: 3, medium: 95, low: 1 }, type: {},
      workflow: state.empty ? {} : { conclusion_review: 8, event_review: 91 } },
  }
  return { data, isPending: state.loading, isError: state.failed, isFetching: false, refetch: vi.fn() }
} }))

describe('工作台结论判断预览', () => {
  beforeEach(() => { state.loading = false; state.failed = false; state.empty = false; state.epoch = 2; state.role = 'analyst'; state.queries = []; vi.clearAllMocks() })
  it('只 GET 三条当前分类，显示分类总数且保留原结论目标', async () => {
    const html = renderToStaticMarkup(<DailyReviewPreview />)
    expect(html).toContain('待人工判断的结论')
    expect(html).toContain('当前分类共 8 项')
    expect(html).toContain('已有结论-3')
    expect(html).not.toContain('已有结论-4')
    expect(html).not.toContain('99')
    expect(html).toContain('href="/conclusions?conclusionId=source%2F1"')
    expect(html).toContain('结论 1 的事实与推断需人工判断')
    expect(html).toContain('href="/suggestions"')
    await state.queries[0].queryFn()
    expect(suggestionsApi.list).toHaveBeenCalledWith({ workflow: 'conclusion_review', status: 'open', limit: 3, offset: 0 })
  })
  it('按当前用户、角色与授权代次隔离预览缓存', () => {
    renderToStaticMarkup(<DailyReviewPreview />)
    expect(state.queries[0].queryKey).toEqual(['suggestions', 'daily-review-preview', 7, 'analyst', 2])
    state.role = 'viewer'; state.epoch++
    renderToStaticMarkup(<DailyReviewPreview />)
    expect(state.queries[1].queryKey).toEqual(['suggestions', 'daily-review-preview', 7, 'viewer', 3])
  })
  it('读取失败隐藏旧缓存，不能将失败显示为零项', () => {
    state.failed = true
    const html = renderToStaticMarkup(<DailyReviewPreview />)
    expect(html).toContain('待判断结论暂不可读')
    expect(html).toContain('数量待确认')
    expect(html).not.toContain('已有结论-1')
    expect(html).not.toContain('当前分类共 0 项')
  })
  it('加载状态不展示已有缓存或假零值', () => {
    state.loading = true
    const html = renderToStaticMarkup(<DailyReviewPreview />)
    expect(html).toContain('正在读取待判断结论')
    expect(html).not.toContain('已有结论-1')
    expect(html).not.toContain('当前分类共 0 项')
  })
  it('空分类只说明暂无该类记录，不声称所有业务完成', () => {
    state.empty = true
    const html = renderToStaticMarkup(<DailyReviewPreview />)
    expect(html).toContain('当前分类共 0 项')
    expect(html).toContain('当前没有待人工判断的结论')
    expect(html).not.toMatch(/全部完成|所有待办已完成|案件办结/)
  })
})
