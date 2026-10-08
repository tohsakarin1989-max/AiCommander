import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import api from './api'
import { createScenarioJob, readScenarioJob, readScenarioOptions, SCENARIO_VERSION, validScenarioResult,
  type RoadScenarioJob, type RoadScenarioOptions, type RoadScenarioResult } from './caseRoadScenarios'
import { RoadScenarioContent, ScenarioSession, toggleScenarioOption } from '../components/CaseResult/CaseRoadScenarios'

vi.mock('./api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
const state = vi.hoisted(() => ({ options: undefined as RoadScenarioOptions | undefined, job: undefined as RoadScenarioJob | undefined,
  error: false, optionsError: null as unknown, jobError: null as unknown,
  jobFetching: false, jobFetched: true, epoch: 1, keys: [] as unknown[][] }))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 7, role: 'analyst' }, sessionEpoch: state.epoch }) }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
    state.keys.push(queryKey)
    const isOptions = queryKey.includes('options')
    const error = isOptions ? state.optionsError : state.jobError
    return { data: isOptions ? state.options : state.job, isError: state.error || !!error, error,
      isPending: false, isFetching: !isOptions && state.jobFetching, isFetchedAfterMount: isOptions || state.jobFetched }
  }, useMutation: () => ({ isPending: false, isError: false, mutate: vi.fn() }), useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))
const binding = { artifactId: 'base', artifactHash: 'a'.repeat(64), resultId: 'result', resultHash: 'b'.repeat(64) }
const optionId = 'c'.repeat(64)
function result(): RoadScenarioResult {
  const row = { asset_id: 12, name: '合成设施', rank: 1, score: 20, eligibility: 'retained' as const,
    conditions: [{ key: 'road', label: '道路', state: 'supported' as const, reason: '可信入口已有计算依据', evidence_refs: ['entry:12'], dependencies: [] }],
    source_context: { state: 'ready', valid_at: '2026-01-01', known_at: '2026-01-02', version_id: 1 }, boundary: '仅条件参考' }
  const base = { id: 'baseline', kind: 'baseline' as const, label: '冻结基准条件', state: 'completed' as const,
    execution: 'reused_frozen_road_evidence', boundary: '不确认来源', calculation: { network_id: 'network', graph_sha256: 'd'.repeat(64) },
    source_versions: { map_snapshot_id: 'map' }, parameters: {}, evidence_refs: [],
    coverage: { recalled: 1, compared: 1, unresolved: 0, complete: true }, rows: [row] }
  return { schema_version: SCENARIO_VERSION, artifact_id: binding.artifactId, artifact_sha256: binding.artifactHash,
    result_id: binding.resultId, result_sha256: binding.resultHash, state: 'completed', boundary: '不代表实际轨迹或准确概率',
    execution_task_created: false, frozen: { pool_sha256: 'e'.repeat(64), known_at: '2026-01-02', algorithm_versions: { scorer: 'frozen-scorer' }, calculation: {} },
    scenarios: [base, { ...base, id: optionId, kind: 'extra_entrance_exclusion', label: '额外排除入口',
      coverage: { recalled: 1, compared: 0, unresolved: 1, complete: true }, rows: [{ ...row, rank: null, score: null, eligibility: 'excluded' }] }],
    observations: [{ asset_id: 12, name: '合成设施', classification: 'condition_dependent', changed_conditions: ['road'],
      ranks: [{ scenario_id: 'baseline', rank: 1, eligibility: 'retained' }, { scenario_id: optionId, rank: null, eligibility: 'excluded' }], reason: '入口排除改变依据', evidence_refs: ['entry:12'] }] }
}
function options(): RoadScenarioOptions {
  return { schema_version: SCENARIO_VERSION, artifact_id: binding.artifactId, artifact_sha256: binding.artifactHash,
    baseline_included: true, max_scenarios: 3, boundary: '冻结依据', capabilities: {},
    road_exclusions: { state: 'not_ready', reason: '严格子图尚未准备好' },
    options: [{ id: optionId, kind: 'extra_entrance_exclusion', label: '排除入口', parameters: {}, evidence_refs: ['entry:12'] }] }
}
function job(): RoadScenarioJob {
  return { event_id: 'job', artifact_id: 'base', status: 'completed', artifact: result(), error: null,
    progress: { scenarios_completed: 2, scenarios_total: 2, road_targets_completed: 0, road_targets_total: 0 }, boundary: '冻结结果' }
}
beforeEach(() => {
  vi.clearAllMocks(); state.options = options(); state.job = job(); state.error = false
  state.optionsError = null; state.jobError = null; state.jobFetching = false; state.jobFetched = true
  state.epoch = 1; state.keys = []
})
describe('受控道路条件比较', () => {
  it('校验相同来源、候选池及最多三情景', () => {
    expect(validScenarioResult(result(), binding)).toBe(true)
    const changed = result(); changed.scenarios[1].rows[0].asset_id = 90
    expect(validScenarioResult(changed, binding)).toBe(false)
    const tooMany = result(); tooMany.scenarios.push(tooMany.scenarios[1], tooMany.scenarios[1])
    expect(validScenarioResult(tooMany, binding)).toBe(false)
    expect(validScenarioResult(result(), { ...binding, resultHash: '0'.repeat(64) })).toBe(false)
  })
  it('服务只提交已登记option引用，不接受用户道路参数', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: options() })
    expect((await readScenarioOptions(binding)).max_scenarios).toBe(3)
    vi.mocked(api.post).mockResolvedValue({ data: { event_id: 'job' } })
    await createScenarioJob(binding, [optionId])
    expect(api.post).toHaveBeenCalledWith('/road-analysis/artifacts/base/scenarios', { artifact_sha256: binding.artifactHash, option_ids: [optionId] })
    await expect(createScenarioJob(binding, [optionId, optionId])).rejects.toThrow('最多选择')
    await expect(createScenarioJob(binding, ['not-a-registered-hash'])).rejects.toThrow('最多选择')
  })
  it('结果读取拒绝串案与非完成任务中夹带的旧结果', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: job() })
    expect((await readScenarioJob(binding, 'job'))?.status).toBe('completed')
    vi.mocked(api.get).mockResolvedValue({ data: { ...job(), status: 'retry' } })
    await expect(readScenarioJob(binding, 'job')).rejects.toThrow('依据不一致')
    vi.mocked(api.get).mockResolvedValue({ data: { ...job(), event_id: 'other' } })
    await expect(readScenarioJob(binding, 'job')).rejects.toThrow('引用不一致')
  })
  it('快速重复勾选也不突破两额外条件上限', () => {
    expect(toggleScenarioOption(['a'], 'a', true)).toEqual(['a'])
    expect(toggleScenarioOption(['a', 'b'], 'c', true)).toEqual(['a', 'b'])
    expect(toggleScenarioOption(['a', 'b'], 'b', false)).toEqual(['a'])
  })
  it('直接解释依据随条件变化，不将顺序当成准确率', () => {
    const html = renderToStaticMarkup(<RoadScenarioContent result={result()} />)
    for (const text of ['依赖所选条件', '条件排除', '不代表确认来源', '复用基准各入口', 'frozen-scorer']) expect(html).toContain(text)
    expect(html).not.toContain('20%')
  })
  it('当前授权错误隐藏缓存，切换会话隔离所有键', () => {
    expect(renderToStaticMarkup(<ScenarioSession {...binding} />)).toContain('合成设施')
    state.error = true
    const html = renderToStaticMarkup(<ScenarioSession {...binding} />)
    expect(html).toContain('旧结果已隐藏'); expect(html).not.toContain('合成设施'); expect(html).not.toContain('排除入口')
    state.error = false; state.epoch = 2
    renderToStaticMarkup(<ScenarioSession {...binding} />)
    expect(state.keys[state.keys.length - 1]?.[2]).toBe(2)
  })
  it('新比较条件409失效仍可只读查看已重新鉴权的冻结历史', () => {
    state.optionsError = { isAxiosError: true, response: { status: 409 } }
    const html = renderToStaticMarkup(<ScenarioSession {...binding} />)
    expect(html).toContain('不能发起新的条件比较')
    expect(html).toContain('冻结历史结果')
    expect(html).toContain('合成设施')
    expect(html).not.toContain('开始条件比较')
    expect(html).not.toContain('需要比较的已登记条件')
  })
  it.each([401, 403, 404])('新比较条件返回%s时不绕过权限隐藏缓存', status => {
    state.optionsError = { isAxiosError: true, response: { status } }
    const html = renderToStaticMarkup(<ScenarioSession {...binding} />)
    expect(html).toContain('旧结果已隐藏')
    expect(html).not.toContain('合成设施')
  })
  it('即使新比较条件409，历史读取撤权仍隐藏所有结果', () => {
    state.optionsError = { isAxiosError: true, response: { status: 409 } }
    state.jobError = { isAxiosError: true, response: { status: 403 } }
    const html = renderToStaticMarkup(<ScenarioSession {...binding} />)
    expect(html).toContain('旧结果已隐藏')
    expect(html).not.toContain('合成设施')
  })
  it('409后等待历史重新鉴权期间不显示前次缓存', () => {
    state.optionsError = { isAxiosError: true, response: { status: 409 } }
    state.jobFetched = false
    expect(renderToStaticMarkup(<ScenarioSession {...binding} />)).not.toContain('合成设施')
    state.jobFetched = true; state.jobFetching = true
    expect(renderToStaticMarkup(<ScenarioSession {...binding} />)).not.toContain('合成设施')
  })
  it('未保留构图源时明确尚未准备好，不当成道路不可达', () => {
    state.options!.options[0] = { ...state.options!.options[0], kind: 'extra_road_exclusion', source_retained: false }
    const html = renderToStaticMarkup(<ScenarioSession {...binding} />)
    expect(html).toContain('尚缺该版本离线构图源包')
    expect(html).toContain('严格子图尚未准备好')
    expect(html).toContain('disabled=')
  })
})
