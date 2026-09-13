import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Workbench, { dailyProfileStatus, formatDailyOccurredTime } from './Workbench'
import { workbenchApi } from '../../services/workbench'
import type { DailyWorkbenchCase } from '../../services/workbench'

const state = vi.hoisted(() => ({
  loading: false, failed: false, empty: false, previewLoading: false, previewFailed: false,
  queries: [] as Array<{ queryKey: unknown[]; queryFn: () => unknown }>,
}))
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 7, role: 'analyst' }, sessionEpoch: 2 }),
}))
vi.mock('react-router-dom', () => ({
  Link: ({ children, to, ...props }: { children: ReactNode; to: string }) => <a href={to} {...props}>{children}</a>,
}))
vi.mock('../../services/workbench', () => ({ workbenchApi: {
  daily: vi.fn(), today: vi.fn(), metrics: vi.fn(), startSession: vi.fn(),
} }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: (options: typeof state.queries[number]) => {
    state.queries.push(options)
    if (options.queryKey[0] === 'suggestions') return {
      isPending: state.previewLoading, isError: state.previewFailed, isFetching: false, refetch: vi.fn(),
      data: { suggestions: [], total: 0, summary: { total: 0, workflow: {}, type: {}, priority: {} } },
    }
    return {
      isPending: state.loading, isError: state.failed, isFetching: false, refetch: vi.fn(),
      data: {
        schema_version: 'daily-workbench-5.0-1', generated_at: '2026-09-12T08:00:00+00:00',
        summary: { total_cases: 301, needs_information: 78, analysis_pending: 15, analysis_ready: 286 },
        cases: state.empty ? [] : [{ id: 42, case_number: '测试案件42', occurred_time: null,
          location: '测试地点', case_status: 'pending', pipeline_status: 'queued', profile_ready: false,
          information_gaps: ['案发时段', '设施类型'], target_path: '/cases?caseId=42' }],
        pagination: { limit: 20, offset: 0, returned: state.empty ? 0 : 1, total: state.empty ? 0 : 301 },
      },
    }
  },
}))

describe('v5.0 只读日常工作台', () => {
  beforeEach(() => { state.loading = false; state.failed = false; state.empty = false; state.previewLoading = false; state.previewFailed = false; state.queries = []; vi.clearAllMocks() })

  it('使用全授权统计，点击案件直接进入详情而非启动旧处理会话', async () => {
    const html = renderToStaticMarkup(<Workbench />)
    expect(html).toContain('301')
    expect(html).toContain('78')
    expect(html).toContain('案发时段')
    expect(html).toContain('等待后台处理')
    expect(html).toContain('href="/cases?caseId=42"')
    expect(html).toContain('href="/suggestions"')
    expect(html).toContain('授权范围内全部案件')
    expect(html).not.toMatch(/完成度|开始处理|开始复核|经验生成|报告生成|任务计时/)
    expect(state.queries).toHaveLength(2)
    expect(state.queries[0].queryKey).toEqual(['workbench-daily', 7, 'analyst', 2, 0])
    await state.queries[0].queryFn()
    expect(workbenchApi.daily).toHaveBeenCalledWith({ limit: 20, offset: 0 })
    expect(workbenchApi.today).not.toHaveBeenCalled()
    expect(workbenchApi.startSession).not.toHaveBeenCalled()
  })

  it('读取失败隐藏缓存内容，不把失败当成零案件', () => {
    state.failed = true
    const html = renderToStaticMarkup(<Workbench />)
    expect(html).toContain('工作台暂不可用')
    expect(html).toContain('href="/cases"')
    expect(html).not.toContain('测试案件42')
    expect(html).not.toContain('301')
  })

  it('没有记录不声称全部案件办结或完成复核', () => {
    state.empty = true
    const html = renderToStaticMarkup(<Workbench />)
    expect(html).toContain('当前没有可展示的案件')
    expect(html).not.toMatch(/全部完成|均已完成|示例案件/)
  })

  it('初次加载展示占位而非假统计', () => {
    state.loading = true
    const html = renderToStaticMarkup(<Workbench />)
    expect(html).toContain('正在读取日常工作')
    expect(html).not.toContain('301')
    expect(html).not.toContain('测试案件42')
  })

  it('处理失败、尚未形成与已有画像明确区分', () => {
    const item = { profile_ready: false, pipeline_status: 'failed' } as DailyWorkbenchCase
    expect(dailyProfileStatus(item)).toBe('处理异常，案件记录已保留')
    expect(dailyProfileStatus({ ...item, pipeline_status: 'not_started' })).toBe('画像尚未形成')
    expect(dailyProfileStatus({ ...item, pipeline_status: 'completed' })).toBe('画像尚未形成')
    expect(dailyProfileStatus({ ...item, profile_ready: true, pipeline_status: 'completed' })).toBe('画像可查看')
  })

  it('待判断预览加载或失败都不阻塞案件表', () => {
    state.previewLoading = true
    const loadingHtml = renderToStaticMarkup(<Workbench />)
    expect(loadingHtml).toContain('正在读取待判断结论')
    expect(loadingHtml).toContain('测试案件42')
    state.previewLoading = false; state.previewFailed = true
    const failedHtml = renderToStaticMarkup(<Workbench />)
    expect(failedHtml).toContain('待判断结论暂不可读')
    expect(failedHtml).toContain('测试案件42')
  })

  it('案件发生时间缺少时区时保留存储时钟，不擅自解释为 UTC', () => {
    expect(formatDailyOccurredTime('2026-09-12T08:30:00')).toBe('2026-09-12 08:30（存储时刻，未注明时区）')
    expect(formatDailyOccurredTime('2026-09-12 08:30:00')).toBe('2026-09-12 08:30（存储时刻，未注明时区）')
    expect(formatDailyOccurredTime('2026-09-12T08:30:00+08:00')).not.toContain('未注明时区')
    expect(formatDailyOccurredTime('2026-09-12T00:30:00Z')).not.toContain('未注明时区')
    expect(formatDailyOccurredTime(null)).toBe('未记录')
  })
})
