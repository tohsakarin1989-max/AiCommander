import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EventCenter from './EventCenter'

const state = vi.hoisted(() => ({ role: 'viewer', error: false, statisticsError: false, statisticsLoading: false }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { role: state.role } }) }))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn(), useSearchParams: () => [new URLSearchParams(), vi.fn()] }))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: ({ queryKey }: { queryKey: string[] }) => ({
    data: queryKey[1] === 'list' ? [{ id: 1, event_number: 'EVENT-1', event_type: 'suspect_activity' }]
      : queryKey[1] === 'statistics' ? { filtered_events: 105, linked_case_count: 2, high_risk_areas: [{ area_name: '历史存档', risk_score: 80 }] } : [],
    isError: queryKey[1] === 'statistics' ? state.statisticsError : state.error && queryKey[1] === 'list',
    isLoading: queryKey[1] === 'statistics' && state.statisticsLoading,
  }),
}))

describe('事件留存功能权限与异常', () => {
  beforeEach(() => { state.role = 'viewer'; state.error = false; state.statisticsError = false; state.statisticsLoading = false })
  it('只读账号保留事件读取而禁用录入和转案件', () => {
    const html = renderToStaticMarkup(<EventCenter />)
    expect(html).toContain('EVENT-1')
    expect(html.match(/class="btn-primary" disabled=""/g)).toHaveLength(2)
  })
  it('分析员保留录入和转案件操作', () => {
    state.role = 'analyst'
    const html = renderToStaticMarkup(<EventCenter />)
    expect(html).not.toContain('disabled=""')
    expect(html).toContain('转案件')
  })
  it('读取失败不把缓存清单和成功空态当作当前结果', () => {
    state.error = true
    const html = renderToStaticMarkup(<EventCenter />)
    expect(html).toContain('事件列表读取失败')
    expect(html).not.toContain('EVENT-1')
    expect(html).not.toContain('暂无事件')
  })

  it('旧区域分值只标为有限历史档案，不冒充当前风险区域', () => {
    const html = renderToStaticMarkup(<EventCenter />)
    expect(html).toContain('<span>旧版区域评估</span><b>1</b>')
    expect(html).toContain('历史高等级档案（最多 5 条），非当前风险')
    expect(html).not.toContain('<span>高风险区域</span>')
    expect(html).not.toContain('需人工核查')
  })

  it.each(['failed', 'loading'])('历史区域统计 %s 不以缓存数量或零风险代替', condition => {
    state.statisticsError = condition === 'failed'
    state.statisticsLoading = condition === 'loading'
    const html = renderToStaticMarkup(<EventCenter />)
    expect(html).toContain(`<span>旧版区域评估</span><b>${condition === 'failed' ? '未读取' : '读取中'}</b>`)
    expect(html).not.toContain('<span>旧版区域评估</span><b>1</b>')
    expect(html).not.toContain('<span>旧版区域评估</span><b>0</b>')
    expect(html).not.toContain('<span>当前范围事件</span><b>105</b>')
    expect(html).not.toContain('<span>当前范围事件</span><b>1</b>')
    expect(html).not.toContain('<span>关联案件</span><b>0</b>')
  })
  it('统计使用后端总体，不拿当前一条清单冒充总量', () => {
    const html = renderToStaticMarkup(<EventCenter />)
    expect(html).toContain('<span>当前范围事件</span><b>105</b>')
    expect(html).toContain('<span>关联案件</span><b>2</b>')
  })
})
