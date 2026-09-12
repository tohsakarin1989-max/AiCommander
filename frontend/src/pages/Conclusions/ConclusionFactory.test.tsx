import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ConclusionFactory from './ConclusionFactory'

const state = vi.hoisted(() => ({ role: 'viewer', error: false, search: '?caseId=42', ready: true, reused: false }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { role: state.role } }) }))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn(), useSearchParams: () => [new URLSearchParams(state.search), vi.fn()] }))
vi.mock('../../services/useCaseWorkspace', () => ({ useCaseWorkspace: () => ({ workspace: state.ready ? { result: { status: 'ready', data: { freshness: 'current' } } } : undefined }) }))
vi.mock('../../components/CaseResult/LatestCaseResult', () => ({ default: ({ caseId }: { caseId: number }) => <div>已有案件成果 #{caseId}</div> }))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: ({ queryKey }: { queryKey: string[] }) => ({
    data: queryKey[0] === 'conclusions' ? [{ id: 1, case_id: 1234, conclusion_type: 'case', status: 'needs_review', risk_level: 'low', confidence: 0,
      ...(state.reused ? { confidence_available: false, model_status: 'reused_case_result' } : {}),
    }] : undefined,
    isError: state.error && queryKey[0] === 'conclusions', isFetching: false, refetch: vi.fn(),
  }),
}))

describe('结论工厂角色边界', () => {
  beforeEach(() => { state.role = 'viewer'; state.error = false; state.search = '?caseId=42'; state.ready = true; state.reused = false })
  it('只读账号禁用生成、草拟和三类复核，保留证据查看', () => {
    const html = renderToStaticMarkup(<ConclusionFactory />)
    expect(html).toContain('只读账号可查看结论')
    expect(html).toMatch(/class="cf-action-btn cf-action-btn--view"/)
    for (const action of ['approve', 'reject', 'flag']) expect(html).toContain(`cf-action-btn--${action}" disabled=""`)
    expect(html.match(/<button[^>]+disabled=""/g)).toHaveLength(5)
    expect(html).not.toContain('旧版草稿预览')
  })
  it('分析员保留复核操作', () => {
    state.role = 'analyst'
    const html = renderToStaticMarkup(<ConclusionFactory />)
    expect(html).not.toMatch(/<button[^>]+disabled=""/)
    expect(html).toContain('通过')
  })
  it('列表错误不展示缓存的待复核记录', () => {
    state.error = true
    const html = renderToStaticMarkup(<ConclusionFactory />)
    expect(html).toContain('结论列表读取失败')
    expect(html).not.toContain('cf-action-btn--approve')
  })
  it('继承案件链接并只读预览已有成果，不要求重新生成草稿', () => {
    state.role = 'analyst'
    const first = renderToStaticMarkup(<ConclusionFactory />)
    expect(first).toContain('已有案件成果 #42')
    expect(first).not.toContain('旧版草稿预览')
    state.search = '?caseId=83'
    const second = renderToStaticMarkup(<ConclusionFactory />)
    expect(second).toContain('已有案件成果 #83')
    expect(second).not.toContain('已有案件成果 #42')
  })
  it('已有成果等待期间禁用复用操作，但已有结论确认仍可用', () => {
    state.role = 'analyst'; state.ready = false
    const html = renderToStaticMarkup(<ConclusionFactory />)
    expect(html).toMatch(/<button class="btn-primary" disabled="">使用已有成果形成结论/)
    expect(html).not.toContain('cf-action-btn--approve" disabled')
  })
  it('复用成果的0占位不展示为准确概率或置信度进度条', () => {
    state.reused = true
    const html = renderToStaticMarkup(<ConclusionFactory />)
    expect(html).toContain('未提供准确概率')
    expect(html).toContain('复用既有案件成果')
    expect(html).not.toContain('cf-confidence__fill')
    expect(html).not.toContain('>0%')
  })
})
