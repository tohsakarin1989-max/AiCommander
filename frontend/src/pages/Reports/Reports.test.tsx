import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Reports from './Reports'

const state = vi.hoisted(() => ({
  meetingId: '', role: 'analyst', listError: false, reportError: false,
  requestedKeys: [] as unknown[][],
}))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { role: state.role } }) }))
vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useSearchParams: () => [new URLSearchParams(state.meetingId ? { meetingId: state.meetingId } : {}), vi.fn()],
}))
vi.mock('./CaseResultsBrowser', () => ({ default: () => <div>案件成果目录</div> }))
vi.mock('@tanstack/react-query', () => ({
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: ({ queryKey, enabled }: { queryKey: unknown[]; enabled?: boolean }) => {
    state.requestedKeys.push(queryKey)
    const key = queryKey[0]
    const failed = key === 'meetings' ? state.listError : key === 'report' && state.reportError
    const data = key === 'meetings' ? []
      : key === 'report-meeting' && enabled !== false ? { meeting_id: state.meetingId, status: 'completed', case_ids: [1] }
        : key === 'stored-reports-for-review' ? [{ id: 1 }]
          : key === 'report' ? { content: { summary: '定向报告摘要' } } : []
    return { data, isLoading: false, isPending: false, isError: failed, error: failed ? new Error('unavailable') : null, refetch: vi.fn() }
  },
}))

describe('报告业务入口与异常状态', () => {
  beforeEach(() => {
    state.meetingId = ''; state.role = 'analyst'; state.listError = false
    state.reportError = false; state.requestedKeys = []
  })

  it('读取并展示深链接会议，即使目标不在默认会议列表', () => {
    state.meetingId = 'history-meeting'
    const html = renderToStaticMarkup(<Reports />)
    expect(state.requestedKeys).toContainEqual(['report-meeting', 'history-meeting'])
    expect(html).toContain('定向报告摘要')
    expect(html).toContain('查看全部会议报告')
  })

  it('会议列表读取失败不显示暂无报告的成功空态', () => {
    state.listError = true
    const html = renderToStaticMarkup(<Reports />)
    expect(html).toContain('会议报告列表读取失败')
    expect(html).not.toContain('暂无分析报告')
  })

  it('报告正文读取失败显示错误，不静默消失或显示缓存正文', () => {
    state.meetingId = 'history-meeting'; state.reportError = true
    const html = renderToStaticMarkup(<Reports />)
    expect(html).toContain('报告读取失败')
    expect(html).not.toContain('定向报告摘要')
  })

  it('只读账号不显示触发写接口的审稿按钮', () => {
    state.role = 'viewer'
    const html = renderToStaticMarkup(<Reports />)
    expect(html).not.toContain('审稿 #1')
    expect(html).toContain('只读账号')
  })

  it('不展示没有筛选逻辑的报告状态标签，保留真实审稿入口', () => {
    const html = renderToStaticMarkup(<Reports />)
    expect(html).not.toContain('rp-filter-row')
    expect(html).not.toContain('rp-filter-chip')
    expect(html).toContain('审稿 #1')
    expect(html).toContain('查看所有会议')
  })
})
