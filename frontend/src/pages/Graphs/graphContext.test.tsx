import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EvidenceGraph from './EvidenceGraph'
import CaseGraph from './CaseGraph'
import type { EvidenceGraphPayload } from '../../services/evidenceGraph'

type Query = { queryKey: unknown[]; enabled?: boolean; queryFn: () => unknown }
const state = vi.hoisted(() => ({ search: '?caseId=2401', epoch: 1, role: 'analyst', failed: false,
  queries: [] as Query[], getCaseGraph: vi.fn(), getCases: vi.fn(), buildSerial: vi.fn(), mutate: vi.fn(),
  setParams: vi.fn(), chartCount: 0,
}))

// Uses the repository's SSR contract-test pattern. URL/query snapshots and error
// rendering are covered; effect lifecycle and pending-request races need DOM/E2E.
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 9, role: state.role }, sessionEpoch: state.epoch }) }))
vi.mock('../../theme/ThemeContext', () => ({ useThemeMode: () => ({ mode: 'light' }) }))
vi.mock('react-router-dom', () => ({ useSearchParams: () => [new URLSearchParams(state.search), state.setParams] }))
vi.mock('../../services/cases', () => ({ caseApi: { getCases: state.getCases } }))
vi.mock('../../services/evidenceGraph', () => ({ evidenceGraphApi: { getCaseGraph: state.getCaseGraph } }))
vi.mock('../../services/analysis', () => ({ analysisApi: { graph: { buildSerial: state.buildSerial } } }))
vi.mock('echarts-for-react', () => ({ default: () => { state.chartCount++; return <div data-testid="chart-boundary" /> } }))
vi.mock('@ant-design/icons', () => ({ DownloadOutlined: () => null, NodeIndexOutlined: () => null,
  SafetyCertificateOutlined: () => null, ShareAltOutlined: () => null, TableOutlined: () => null, FilterOutlined: () => null }))
vi.mock('antd', () => ({
  App: { useApp: () => ({ message: { info: vi.fn() } }) },
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  Alert: ({ message }: { message: ReactNode }) => <div>{message}</div>,
  Select: () => null, Switch: () => null, Table: () => null,
  Input: ({ value, placeholder }: { value: string; placeholder: string }) => <input value={value} placeholder={placeholder} readOnly />,
}))

function graphPayload(id: number): EvidenceGraphPayload {
  return {
    case_id: id, case_number: `精确证据案件-${id}`, generated_at: '2026-09-12T00:00:00Z',
    source_snapshot: { algorithm: 'sha256', data_version: `version-${id}`, scope: `case:${id}` },
    summary: { total_nodes: 1, total_edges: 0, source_nodes: 1, confirmed_nodes: 0,
      inferred_nodes: 0, gap_nodes: 0, traceability_rate: 100, graph_health: 'complete' },
    nodes: [{ id: `case:${id}`, type: 'case', layer: 'subject', label: `精确证据案件-${id}`,
      subtitle: '', status: 'recorded', confidence: 1, source_ref: `case:${id}`, is_human_confirmed: false, detail: {} }],
    edges: [], review_queue: [], boundary: { read_only: true, statements: ['不自动确认案件关系'] },
  }
}

vi.mock('@tanstack/react-query', () => ({
  useQuery: (query: Query) => {
    state.queries.push(query)
    const isGraph = query.queryKey[0] === 'evidence-graph'
    const data = isGraph && query.enabled !== false
      ? graphPayload(Number(query.queryKey[1])) : isGraph ? undefined : [{ id: 1, case_number: '近期案件' }]
    return { data, isLoading: false, isFetching: false, isSuccess: !state.failed, isError: state.failed, refetch: vi.fn() }
  },
  useMutation: () => ({ isPending: false, mutate: state.mutate }),
}))

describe('图谱案件上下文（SSR 契约）', () => {
  beforeEach(() => {
    state.search = '?caseId=2401'; state.epoch = 1; state.role = 'analyst'; state.failed = false
    state.queries = []; state.chartCount = 0; vi.clearAllMocks()
  })
  it('证据图谱精确读取 URL 案件，而非近期 50 案中的第一条', async () => {
    const html = renderToStaticMarkup(<EvidenceGraph />)
    expect(html).toContain('精确证据案件-2401')
    const query = state.queries.find(item => item.queryKey[0] === 'evidence-graph')!
    expect(query.queryKey).toEqual(['evidence-graph', 2401, 5, 9, 1])
    await query.queryFn()
    expect(state.getCaseGraph).toHaveBeenCalledWith(2401, { wellRadiusKm: 5 })
    expect(state.setParams).not.toHaveBeenCalled()
    expect(state.buildSerial).not.toHaveBeenCalled()
    expect(state.mutate).not.toHaveBeenCalled()
  })
  it('新的 URL 与授权代次快照改变查询范围，不继续渲染旧案件内容', () => {
    renderToStaticMarkup(<EvidenceGraph />)
    state.search = '?caseId=2402'; state.epoch++; state.queries = []
    const html = renderToStaticMarkup(<EvidenceGraph />)
    expect(html).toContain('精确证据案件-2402')
    expect(html).not.toContain('精确证据案件-2401')
    expect(state.queries.find(query => query.queryKey[0] === 'evidence-graph')?.queryKey)
      .toEqual(['evidence-graph', 2402, 5, 9, 2])
  })
  it('图谱读取撤权失败时隐藏仍在缓存中的图谱和证据摘要', () => {
    state.failed = true
    const html = renderToStaticMarkup(<EvidenceGraph />)
    expect(html).toContain('证据图谱暂不可用')
    expect(html).not.toContain('精确证据案件-2401')
    expect(html).not.toContain('证据图谱摘要')
    expect(state.chartCount).toBe(0)
  })
  it('无效 URL 不发起图谱查询或改选近期案件', () => {
    state.search = '?caseId=1invalid'
    const html = renderToStaticMarkup(<EvidenceGraph />)
    expect(state.queries.find(query => query.queryKey[0] === 'evidence-graph')?.enabled).toBe(false)
    expect(html).not.toContain('精确证据案件-')
    expect(state.setParams).not.toHaveBeenCalled()
  })
  it('案件关系图页面只读取候选列表，URL 到达不会自动启动生成', async () => {
    const html = renderToStaticMarkup(<CaseGraph />)
    expect(html).toContain('待生成')
    expect(state.queries[0].queryKey).toEqual(['cases', 'recent50', 9, 1])
    await state.queries[0].queryFn()
    expect(state.getCases).toHaveBeenCalledWith({ limit: 50 })
    expect(state.buildSerial).not.toHaveBeenCalled()
    expect(state.mutate).not.toHaveBeenCalled()
    state.search = '?caseId=2402'; state.epoch++; state.queries = []; state.role = 'viewer'
    const viewerHtml = renderToStaticMarkup(<CaseGraph />)
    expect(viewerHtml).toContain('只读账号不触发关系图谱生成')
    expect(state.queries[0].queryKey).toEqual(['cases', 'recent50', 9, 2])
    expect(state.mutate).not.toHaveBeenCalled()
  })
})
