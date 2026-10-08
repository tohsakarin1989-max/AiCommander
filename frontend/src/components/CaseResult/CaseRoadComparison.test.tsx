import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CaseRoadComparison, { RoadComparisonProgress } from './CaseRoadComparison'
import { readAutomaticRoadComparison, type AutomaticRoadComparison, type FacilityComparisonProgress } from '../../services/roadAnalysis'

const state = vi.hoisted(() => ({
  auth: { user: { id: 1, role: 'analyst' }, sessionEpoch: 1 },
  effects: [] as (() => void | (() => void))[], values: [] as unknown[], cursor: 0,
}))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(),
  useState: (initial: unknown) => {
    const index = state.cursor++
    if (!(index in state.values)) state.values[index] = initial
    return [state.values[index], (value: unknown) => {
      state.values[index] = typeof value === 'function' ? value(state.values[index]) : value
    }]
  },
  useCallback: (callback: unknown) => callback,
  useEffect: (effect: () => void | (() => void)) => state.effects.push(effect),
}))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => state.auth }))
vi.mock('../../services/roadAnalysis', async original => ({ ...await original<typeof import('../../services/roadAnalysis')>(),
  readAutomaticRoadComparison: vi.fn(), readRoadArtifact: vi.fn(),
}))
vi.mock('./CaseResultDownload', () => ({ default: () => null }))
vi.mock('./CaseReachableRoads', () => ({ default: () => null }))
vi.mock('./CaseRoadPath', () => ({ default: () => null }))
vi.mock('./CaseRoadHistory', () => ({ default: () => null }))
vi.mock('./CaseFacilityComparison', () => ({ default: () => null }))
vi.mock('./FacilityEvaluationArchive', () => ({ default: () => null }))

const progress = (): FacilityComparisonProgress => ({ phase: 'roads', scanned: 12, scan_complete: true,
  candidate_pool_size: 12, candidate_pool_limit: 100, entrance_facilities_checked: 12,
  entrance_facilities_total: 12, entrance_check_complete: true, road_targets_completed: 10,
  road_targets_total: 12, road_complete: false, dependency_policy: 'whole_authorized_scope_conservative',
  boundary: '最多展示三项不等于只计算三个设施；候选池上限100，未选尽时不宣称全域最优。' })
const pending = (): AutomaticRoadComparison => ({ result_id: 'result', content_sha256: 'hash',
  status: 'processing', artifact: null, progress: progress() })
const props = { resultId: 'result', hash: 'hash' }
function session() {
  state.cursor = 0
  const wrapper = CaseRoadComparison(props) as ReactElement<typeof props>
  return (wrapper.type as (value: typeof props) => ReactElement)(wrapper.props)
}
async function start() {
  session()
  const cleanup = state.effects.shift()!()
  await Promise.resolve(); await Promise.resolve()
  return cleanup as () => void
}

describe('道路进度日常状态', () => {
  beforeEach(() => {
    vi.resetAllMocks(); vi.useFakeTimers()
    state.auth = { user: { id: 1, role: 'analyst' }, sessionEpoch: 1 }
    state.effects = []; state.values = []; state.cursor = 0
    vi.stubGlobal('document', { hidden: false })
    vi.stubGlobal('window', { addEventListener: vi.fn(), removeEventListener: vi.fn() })
  })
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

  it.each([['scan', '扫描候选设施'], ['entrances', '核验候选设施入口'], ['roads', '分批比较道路目标']] as const)(
    '展示%s阶段实际数量，不生成百分比', (phase, label) => {
      const html = renderToStaticMarkup(<RoadComparisonProgress progress={{ ...progress(), phase }} />)
      expect(html).toContain(label)
      expect(html).toContain('已扫描 12 个设施')
      expect(html).toContain('入口核验已处理 12 / 12 个候选设施')
      expect(html).toContain('道路目标已处理 10 个')
      expect(html).toContain('继续处理不代表失败')
      expect(html).not.toContain('%')
    })
  it('目标总数未知时明确未知，不说全域完成或补零', () => {
    const html = renderToStaticMarkup(<RoadComparisonProgress progress={{ ...progress(), road_targets_completed: 0, road_targets_total: null }} />)
    expect(html).toContain('总数尚未确定')
    expect(html).toContain('尚未形成完整道路比较成果')
    expect(html).not.toContain('当前固定目标共 0')
    expect(html).not.toContain('全域完成')
  })
  it.each(['frozen_inputs_unavailable', 'frozen_inputs_changed'] as const)('轮询发现%s立即清除旧计数', async reason => {
    vi.mocked(readAutomaticRoadComparison).mockResolvedValueOnce(pending()).mockResolvedValueOnce({
      ...pending(), status: 'unavailable', progress: undefined, reason,
    })
    const cleanup = await start()
    expect(renderToStaticMarkup(session())).toContain('道路目标已处理 10 个')
    await vi.advanceTimersByTimeAsync(10000)
    const html = renderToStaticMarkup(session())
    expect(html).toContain('已隐藏旧进度')
    expect(html).not.toContain('道路目标已处理')
    expect(state.values[6]).toBeNull()
    cleanup()
  })
  it('已完成不保留处理中进度', async () => {
    vi.mocked(readAutomaticRoadComparison).mockResolvedValueOnce(pending()).mockResolvedValueOnce({
      result_id: 'result', content_sha256: 'hash', status: 'completed',
      artifact: { id: 'artifact', content_sha256: 'a'.repeat(64), created_at: '2026-10-05', content: {
        schema_version: 'case-road-comparison-4.2.0-1', result_id: 'result', content_sha256: 'hash',
        map_snapshot_id: 'map', targets: [], information_gaps: [], matrix: null, boundary: '合成附件',
      } },
    })
    const cleanup = await start()
    await vi.advanceTimersByTimeAsync(10000)
    expect(state.values[6]).toBeNull()
    expect(renderToStaticMarkup(session())).not.toContain('道路目标已处理')
    cleanup()
  })
  it('等待运行条件不保留先前扫描进度，也不显示计算失败', async () => {
    vi.mocked(readAutomaticRoadComparison).mockResolvedValueOnce(pending()).mockResolvedValueOnce({
      ...pending(), status: 'waiting_network', progress: undefined,
    })
    const cleanup = await start()
    await vi.advanceTimersByTimeAsync(10000)
    const html = renderToStaticMarkup(session())
    expect(state.values[6]).toBeNull()
    expect(html).toContain('系统会在可用后继续')
    expect(html).not.toContain('道路目标已处理')
    expect(html).not.toContain('道路比较暂不可用')
    cleanup()
  })
  it('账号、会话或材料变更立即换独立组件状态', () => {
    const first = CaseRoadComparison(props).key
    state.auth.sessionEpoch = 2
    expect(CaseRoadComparison(props).key).not.toBe(first)
    state.auth = { user: { id: 2, role: 'viewer' }, sessionEpoch: 1 }
    expect(CaseRoadComparison(props).key).not.toBe(first)
    state.auth = { user: { id: 1, role: 'analyst' }, sessionEpoch: 1 }
    expect(CaseRoadComparison({ ...props, resultId: 'other' }).key).not.toBe(first)
  })
  it('会话失效清除已显示进度并阻止旧请求继续轮询', async () => {
    vi.mocked(readAutomaticRoadComparison).mockResolvedValue(pending())
    const cleanup = await start()
    const expired = vi.mocked(window.addEventListener).mock.calls.find(call => call[0] === 'aic:auth-expired')![1] as () => void
    expired()
    expect(state.values[6]).toBeNull()
    expect(renderToStaticMarkup(session())).not.toContain('道路目标已处理')
    await vi.advanceTimersByTimeAsync(10000)
    expect(readAutomaticRoadComparison).toHaveBeenCalledOnce()
    expect(vi.mocked(readAutomaticRoadComparison).mock.calls[0][2].aborted).toBe(true)
    cleanup()
  })
})
