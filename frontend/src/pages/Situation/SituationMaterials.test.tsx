import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { SituationBriefResult } from '../../services/intelligenceFlow'
import SituationWorkbench from './SituationWorkbench'

const state = vi.hoisted(() => ({ epoch: 1, failed: false, status: 403, data: undefined as SituationBriefResult | undefined, keys: [] as unknown[][] }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 7 }, sessionEpoch: state.epoch }) }))
vi.mock('react-router-dom', () => ({ Link: ({ to, children }: { to: string; children: ReactNode }) => <a href={to}>{children}</a> }))
vi.mock('antd', () => ({ App: { useApp: () => ({ message: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }) },
  Select: () => <span>条件选择</span>, Input: () => <input /> }))
vi.mock('@tanstack/react-query', () => ({ useMutation: () => ({ mutate: vi.fn() }), useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
  state.keys.push(queryKey)
  return { data: queryKey[0] === 'automatic-situation-brief' ? state.data : undefined,
    isError: queryKey[0] === 'automatic-situation-brief' && state.failed, error: { response: { status: state.status } },
    isPending: false, isFetching: false, refetch: vi.fn() }
} }))
vi.mock('./SituationChart', () => ({ default: () => <p>历史图表</p> }))
vi.mock('./SpatialCoveragePanel', () => ({ default: () => <p>覆盖核验入口</p> }))
vi.mock('./RoadChanges', () => ({ default: () => <p>道路变化</p> }))

describe('自动态势直达同周期固定材料', () => {
  beforeEach(() => {
    state.epoch = 1; state.failed = false; state.status = 403; state.keys = []
    state.data = { id: 'same-period-brief', period_type: 'weekly', period_start: '2026-09-21', period_end: '2026-09-28',
      status: 'ready', summary: '已授权周期摘要', algorithm_version: 'v1', scope_policy_version: '1', evidence_refs: [], information_gaps: [],
      generated_at: '2026-09-29', recommendations: [], comparison_snapshot: { timezone: 'Asia/Shanghai',
        previous: { start: '2026-09-14', end: '2026-09-21', case_count: 31, profile_versions_generated: 1 },
        current: { start: '2026-09-21', end: '2026-09-28', case_count: 987654, profile_versions_generated: 2 } } }
  })
  it('使用已读取简报ID直达统一材料，不重算周期或新增生成入口', () => {
    const html = renderToStaticMarkup(<SituationWorkbench />)
    expect(html).toContain('/reports?kind=situation&amp;resultId=same-period-brief')
    expect(html).toContain('使用当前自动简报的同一周期与内容，不重新计算')
    expect(html).toContain('987654'); expect(html).toContain('覆盖核验入口')
    expect(state.keys).toContainEqual(['automatic-situation-brief', '7:1'])
    state.epoch = 2
    renderToStaticMarkup(<SituationWorkbench />)
    expect(state.keys).toContainEqual(['automatic-situation-brief', '7:2'])
  })
  it.each([403, 404, 500])('读取失败 %s 时隐藏历史摘要、周期数量和材料链接', status => {
    state.failed = true; state.status = status
    const html = renderToStaticMarkup(<SituationWorkbench />)
    expect(html).not.toContain('same-period-brief'); expect(html).not.toContain('已授权周期摘要'); expect(html).not.toContain('987654')
    expect(html).toContain(status === 404 ? '尚无简报' : '暂不可用')
  })
  it.each(['unavailable', 'restricted'])('受限状态 %s 即使误带正文也不暴露缓存', status => {
    state.data!.status = status
    const html = renderToStaticMarkup(<SituationWorkbench />)
    expect(html).not.toContain('same-period-brief'); expect(html).not.toContain('已授权周期摘要'); expect(html).not.toContain('987654')
    expect(html).toContain('暂不可用')
  })
})
