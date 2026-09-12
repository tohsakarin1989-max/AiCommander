import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Meetings from './Meetings'

const state = vi.hoisted(() => ({ role: 'analyst', id: '', status: 'completed', error: false,
  queries: [] as Array<{ queryKey: unknown[]; enabled?: boolean; queryFn: () => unknown }> }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { role: state.role } }) }))
vi.mock('react-router-dom', () => ({ useSearchParams: () => [new URLSearchParams({ meetingId: state.id })] }))
vi.mock('../../services/websocket', () => ({ useMeetingProgress: () => ({ progress: null, isConnected: false }) }))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: (options: typeof state.queries[number]) => {
    state.queries.push(options)
    const name = options.queryKey[0]
    const data = name === 'meeting' && options.enabled ? {
      meeting_id: state.id, status: state.status, case_ids: [998], analyst_model_ids: [2], moderator_model_id: 1,
      created_at: '2026-09-12T10:00:00',
    } : name === 'meeting' ? undefined : name === 'report' ? { content: { summary: '历史会议完整摘要' } } : []
    return { data, isLoading: false, isError: name === 'meetings' && state.error }
  },
}))

describe('历史圆桌会议入口', () => {
  beforeEach(() => { state.role = 'analyst'; state.id = ''; state.error = false; state.status = 'completed'; state.queries = [] })

  it('深链接直接读取不在默认列表的历史会议', () => {
    state.id = 'MEET-OLD-998'
    const html = renderToStaticMarkup(<Meetings />)
    expect(state.queries.find(q => q.queryKey[0] === 'meeting')).toMatchObject({ queryKey: ['meeting', state.id], enabled: true })
    expect(html).toContain('MEET-OLD-998')
    expect(html).toContain('历史会议完整摘要')
  })

  it('分析员读取安全模型目录，不请求管理员会议配置且保留发起操作', () => {
    const html = renderToStaticMarkup(<Meetings />)
    expect(state.queries.some(q => q.queryKey[0] === 'meeting-model-options')).toBe(true)
    expect(state.queries.find(q => q.queryKey[0] === 'meetingConfig')?.enabled).toBe(false)
    expect(html).toMatch(/<button class="btn-accent" style=/)
  })

  it('只读账号不能发起会议或生成结论', () => {
    state.role = 'viewer'; state.id = 'MEET-OLD-998'
    const html = renderToStaticMarkup(<Meetings />)
    expect(html).toContain('只读账号可查看会议记录')
    expect(html).toMatch(/class="btn-accent" disabled=""/)
    expect(html).toMatch(/class="btn-accent-sm" disabled=""/)
  })

  it('处理中不提前请求未生成报告，列表错误不显示无记录', () => {
    state.id = 'MEET-RUN'; state.status = 'processing'; state.error = true
    const html = renderToStaticMarkup(<Meetings />)
    expect(state.queries.find(q => q.queryKey[0] === 'report')?.enabled).toBe(false)
    expect(html).toContain('会议列表读取失败')
    expect(html).not.toContain('尚无会议记录')
  })
})
