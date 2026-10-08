import api from './api'
import { validFacilityConditions, type FacilityConditionComparison } from './facilityConditions'

export const SCENARIO_VERSION = 'case-road-scenarios-8.3-1'
export type ScenarioKind = 'baseline' | 'production_period' | 'reference_vehicle' | 'extra_entrance_exclusion' | 'extra_road_exclusion'
export interface RoadScenarioOption {
  id: string; kind: Exclude<ScenarioKind, 'baseline'>; label: string
  parameters: Record<string, unknown>; evidence_refs: string[]; source_retained?: boolean
}
export interface RoadScenarioOptions {
  schema_version: typeof SCENARIO_VERSION; artifact_id: string; artifact_sha256: string
  options: RoadScenarioOption[]; max_scenarios: 3; baseline_included: true; boundary: string
  capabilities: Record<string, { state: string }>
  road_exclusions: { state: 'available' | 'not_ready'; reason: string }
}
export interface RoadScenarioResult {
  schema_version: typeof SCENARIO_VERSION; artifact_id: string; artifact_sha256: string
  result_id: string; result_sha256: string; state: 'completed' | 'partial'; boundary: string
  frozen: { pool_sha256: string; known_at: string; algorithm_versions: Record<string, string>; calculation: Record<string, unknown> }
  scenarios: Array<{
    id: string; kind: ScenarioKind; label: string; state: 'completed' | 'partial'; boundary: string
    execution: string; calculation: Record<string, unknown>; source_versions: Record<string, unknown>
    parameters: Record<string, unknown>; evidence_refs: string[]
    coverage: { recalled: number; compared: number; unresolved: number; complete: boolean }
    rows: FacilityConditionComparison['rows']
  }>
  observations: Array<{ asset_id: number; name: string
    classification: 'retained_across_scenarios' | 'excluded_in_all' | 'condition_dependent' | 'insufficient_data'
    changed_conditions: string[]; ranks: Array<{ scenario_id: string; rank: number | null; eligibility: 'retained' | 'excluded' | 'unresolved' }>
    reason: string; evidence_refs: string[] }>
  execution_task_created: false
}
export interface RoadScenarioJob {
  event_id: string; artifact_id: string; status: 'pending' | 'processing' | 'retry' | 'completed' | 'failed' | 'superseded' | 'cancelled'
  artifact: RoadScenarioResult | null; error: string | null; boundary: string
  progress: { scenarios_completed: number; scenarios_total: number; road_targets_completed: number; road_targets_total: number }
}
export interface ScenarioBinding { artifactId: string; artifactHash: string; resultId: string; resultHash: string }
const kinds: ScenarioKind[] = ['baseline', 'production_period', 'reference_vehicle', 'extra_entrance_exclusion', 'extra_road_exclusion']
const hash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(item => typeof item === 'string')
const count = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0

export function validScenarioResult(value: RoadScenarioResult, binding: ScenarioBinding): boolean {
  if (!value || value.schema_version !== SCENARIO_VERSION || value.artifact_id !== binding.artifactId
    || value.artifact_sha256 !== binding.artifactHash || value.result_id !== binding.resultId || value.result_sha256 !== binding.resultHash
    || !['completed', 'partial'].includes(value.state) || value.execution_task_created !== false || typeof value.boundary !== 'string'
    || !hash(value.frozen?.pool_sha256) || typeof value.frozen.known_at !== 'string' || !value.frozen.algorithm_versions
    || !Array.isArray(value.scenarios) || value.scenarios.length < 2 || value.scenarios.length > 3
    || value.scenarios[0]?.kind !== 'baseline' || value.scenarios[0]?.id !== 'baseline'
    || new Set(value.scenarios.map(row => row.id)).size !== value.scenarios.length) return false
  const ids = value.scenarios[0].rows?.map(row => row.asset_id)
  if (!ids || !value.scenarios.every((row, index) => kinds.includes(row.kind) && (index === 0 || row.kind !== 'baseline' && hash(row.id))
    && typeof row.label === 'string' && ['completed', 'partial'].includes(row.state) && typeof row.execution === 'string'
    && !!row.calculation && !!row.source_versions && strings(row.evidence_refs) && !!row.parameters
    && !!row.coverage && count(row.coverage.recalled) && count(row.coverage.compared) && count(row.coverage.unresolved)
    && row.coverage.compared + row.coverage.unresolved <= row.coverage.recalled && typeof row.coverage.complete === 'boolean'
    && validFacilityConditions({ schema_version: 'facility-conditions-6.3-1', rows: row.rows, priority_gaps: [], boundary: row.boundary }, row.coverage.recalled)
    && JSON.stringify(row.rows.map(item => item.asset_id)) === JSON.stringify(ids))) return false
  return Array.isArray(value.observations) && value.observations.length === ids.length
    && new Set(value.observations.map(row => row.asset_id)).size === ids.length
    && value.observations.every(row => ids.includes(row.asset_id) && typeof row.name === 'string' && typeof row.reason === 'string'
      && ['retained_across_scenarios', 'excluded_in_all', 'condition_dependent', 'insufficient_data'].includes(row.classification)
      && strings(row.changed_conditions) && strings(row.evidence_refs) && Array.isArray(row.ranks) && row.ranks.length === value.scenarios.length
      && row.ranks.every((rank, index) => rank.scenario_id === value.scenarios[index].id
        && rank.rank === value.scenarios[index].rows.find(item => item.asset_id === row.asset_id)?.rank
        && rank.eligibility === value.scenarios[index].rows.find(item => item.asset_id === row.asset_id)?.eligibility))
}
function validateJob(value: RoadScenarioJob, binding: ScenarioBinding): RoadScenarioJob {
  if (!value || typeof value.event_id !== 'string' || value.artifact_id !== binding.artifactId
    || !['pending', 'processing', 'retry', 'completed', 'failed', 'superseded', 'cancelled'].includes(value.status)
    || !value.progress || !Object.values(value.progress).every(count) || value.progress.scenarios_total < 2 || value.progress.scenarios_total > 3
    || value.progress.scenarios_completed > value.progress.scenarios_total
    || value.progress.road_targets_completed > value.progress.road_targets_total || typeof value.boundary !== 'string'
    || (value.status === 'completed' ? !validScenarioResult(value.artifact!, binding) : value.artifact !== null)) throw new Error('条件比较依据不一致')
  return value
}
export async function readScenarioOptions(binding: ScenarioBinding, signal?: AbortSignal): Promise<RoadScenarioOptions> {
  const { data } = await api.get<RoadScenarioOptions>(`/road-analysis/artifacts/${encodeURIComponent(binding.artifactId)}/scenario-options`, { signal })
  if (!data || data.schema_version !== SCENARIO_VERSION || data.artifact_id !== binding.artifactId || data.artifact_sha256 !== binding.artifactHash
    || data.max_scenarios !== 3 || data.baseline_included !== true || typeof data.boundary !== 'string'
    || !['available', 'not_ready'].includes(data.road_exclusions?.state) || typeof data.road_exclusions.reason !== 'string'
    || !Array.isArray(data.options) || new Set(data.options.map(row => row.id)).size !== data.options.length
    || !data.options.every(row => hash(row.id) && kinds.includes(row.kind) && typeof row.label === 'string' && !!row.parameters && strings(row.evidence_refs)))
    throw new Error('可比较条件尚未核验')
  return data
}
export async function createScenarioJob(binding: ScenarioBinding, optionIds: string[]) {
  if (optionIds.length < 1 || optionIds.length > 2 || new Set(optionIds).size !== optionIds.length || !optionIds.every(hash))
    throw new Error('最多选择两套条件，基准条件自动保留')
  const { data } = await api.post<{ event_id: string }>(`/road-analysis/artifacts/${encodeURIComponent(binding.artifactId)}/scenarios`,
    { artifact_sha256: binding.artifactHash, option_ids: optionIds })
  if (typeof data?.event_id !== 'string') throw new Error('任务创建尚未确认')
  return data
}
export async function readScenarioJob(binding: ScenarioBinding, eventId: string | null, signal?: AbortSignal): Promise<RoadScenarioJob | null> {
  if (eventId) {
    const { data } = await api.get<RoadScenarioJob>(`/road-analysis/scenarios/${encodeURIComponent(eventId)}`, { signal })
    if (data?.event_id !== eventId) throw new Error('任务引用不一致')
    return validateJob(data, binding)
  }
  const { data } = await api.get<{ job: RoadScenarioJob | null }>(`/road-analysis/artifacts/${encodeURIComponent(binding.artifactId)}/scenarios`, { signal })
  return data.job === null ? null : validateJob(data.job, binding)
}
export async function cancelScenarioJob(eventId: string) {
  await api.post(`/road-analysis/scenarios/${encodeURIComponent(eventId)}/cancel`)
}
