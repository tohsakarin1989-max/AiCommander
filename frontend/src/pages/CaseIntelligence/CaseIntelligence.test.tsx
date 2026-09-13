import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CaseIntelligence, { intelligenceCaseId } from './CaseIntelligence'

const state = vi.hoisted(() => ({ search: '?caseId=42', role: 'analyst',
  queries: [] as Array<{ queryKey: unknown[]; enabled?: boolean }>, failed: false,
}))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 2, role: state.role }, sessionEpoch: 1 }) }))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn(), useSearchParams: () => [new URLSearchParams(state.search), vi.fn()] }))
vi.mock('../../components/CaseResult/LatestCaseResult', () => ({ default: ({ caseId }: { caseId: number }) => <div>统一成果案件 #{caseId}</div> }))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: (options: typeof state.queries[number]) => {
    state.queries.push(options)
    const name = options.queryKey[0]
    return { isLoading: false, isFetching: false,
      isError: name === 'case-intelligence-selected' && state.failed,
      data: name === 'cases-for-intelligence' ? [] : name === 'case-intelligence-selected'
        ? { id: options.queryKey[1], case_number: '超出近期列表的案件' } : undefined,
    }
  },
}))

describe('案件上下文与按需旧版工具', () => {
  beforeEach(() => { state.search = '?caseId=42'; state.role = 'analyst'; state.failed = false; state.queries = [] })
  it('当前URL决定选中案件，不受最近200条案件列表限制', () => {
    const html = renderToStaticMarkup(<CaseIntelligence />)
    expect(html).toContain('统一成果案件 #42')
    expect(state.queries.find(item => item.queryKey[0] === 'case-intelligence-selected')?.queryKey[1]).toBe(42)
    expect(state.queries.find(item => item.queryKey[0] === 'cases-for-intelligence')?.enabled).toBe(false)
    state.search = '?caseId=999'
    expect(renderToStaticMarkup(<CaseIntelligence />)).toContain('统一成果案件 #999')
  })
  it('日常查看不自动请求旧版分析、图谱或经验生成相关资料', () => {
    renderToStaticMarkup(<CaseIntelligence />)
    for (const key of ['case-intelligence-workbench', 'case-intelligence-llm-context', 'case-diagram',
      'knowledge-assets', 'experience-reuse-recommendations', 'knowledge-reuse-records']) {
      expect(state.queries.find(item => item.queryKey[0] === key)?.enabled).toBe(false)
    }
  })
  it('明确经验确认链接仍能打开兼容工具，普通查看不要求创建经验卡', () => {
    state.search = '?caseId=42&tool=experience'
    const html = renderToStaticMarkup(<CaseIntelligence />)
    expect(html).toContain('收起旧版分析工具')
    expect(html).toContain('不要求每起案件保存经验卡或报告')
    expect(state.queries.find(item => item.queryKey[0] === 'knowledge-assets')?.enabled).toBe(true)
  })
  it('无效编号和读取失败都不静默改为其他案件', () => {
    expect(intelligenceCaseId(new URLSearchParams('?caseId=-1'))).toBeUndefined()
    state.failed = true
    expect(renderToStaticMarkup(<CaseIntelligence />)).toContain('不自动切换到其他案件')
  })
})
