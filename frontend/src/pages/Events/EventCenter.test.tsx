import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EventCenter from './EventCenter'

const state = vi.hoisted(() => ({ role: 'viewer', error: false }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { role: state.role } }) }))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: ({ queryKey }: { queryKey: string[] }) => ({
    data: queryKey.length === 1 ? [{ id: 1, event_number: 'EVENT-1', event_type: 'suspect_activity' }] : [],
    isError: state.error && queryKey.length === 1, isLoading: false,
  }),
}))

describe('事件留存功能权限与异常', () => {
  beforeEach(() => { state.role = 'viewer'; state.error = false })
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
})
