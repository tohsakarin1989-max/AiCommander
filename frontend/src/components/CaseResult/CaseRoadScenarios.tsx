import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Checkbox, Space, Tag } from 'antd'
import { isAxiosError } from 'axios'
import { useAuth } from '../../auth/AuthContext'
import { cancelScenarioJob, createScenarioJob, readScenarioJob, readScenarioOptions, validScenarioResult,
  type RoadScenarioResult, type ScenarioBinding } from '../../services/caseRoadScenarios'
import './CaseRoadScenarios.css'

const active = (status?: string) => ['pending', 'processing', 'retry'].includes(status || '')
const classes = { retained_across_scenarios: '各情景均保留依据', condition_dependent: '依赖所选条件',
  excluded_in_all: '各情景均排除', insufficient_data: '部分条件仍无法判断' }
const conditionNames: Record<string, string> = { road: '道路与入口', source: '资料适用性', oil: '油品', facility: '设施属性', production: '生产条件', history: '历史参考' }
export function toggleScenarioOption(previous: string[], id: string, checked: boolean): string[] {
  if (!checked) return previous.filter(value => value !== id)
  return previous.includes(id) || previous.length >= 2 ? previous : [...previous, id]
}

export function RoadScenarioContent({ result }: { result: RoadScenarioResult }) {
  return <section className="case-result__scenarios" aria-label="条件比较结果">
    <p>{result.state === 'partial' ? '已有部分比较结果；未知或未完成部分不能作为确定结论。' : '已完成本固定候选池的条件比较。'} 不代表确认来源或实际路线。</p>
    <p>资料截止：{result.frozen.known_at}。最多三套条件均使用同一批设施和同一评分规则。</p>
    <div className="case-result__scenario-table"><table>
      <caption>依据是否依赖条件（仅列冻结候选，不代表全域最优）</caption>
      <thead><tr><th scope="col">设施</th><th scope="col">比较说明</th>{result.scenarios.map(row => <th scope="col" key={row.id}>{row.label}</th>)}</tr></thead>
      <tbody>{result.observations.map(row => <tr key={row.asset_id}>
        <th scope="row">{row.name}</th><td>{classes[row.classification]}{row.changed_conditions.length > 0 && <p>变化条件：{row.changed_conditions.map(key => conditionNames[key] || key).join('、')}</p>}</td>
        {row.ranks.map(rank => <td key={rank.scenario_id}>{rank.eligibility === 'excluded' ? '条件排除' : rank.eligibility === 'unresolved' ? '无法判断' : `参考顺序 ${rank.rank}`}</td>)}
      </tr>)}</tbody>
    </table></div>
    <details><summary>查看逐项依据、未知部分与版本</summary>
      {result.scenarios.map(scenario => <section key={scenario.id}><h5>{scenario.label}</h5>
        <p>{scenario.execution === 'reused_frozen_road_evidence' ? '复用基准各入口的冻结道路计算，只改变声明条件。'
          : scenario.execution === 'road_service_unavailable' ? '道路服务不可用，本情景未取得完整道路结果；不以直线距离代替。'
          : scenario.execution === 'network_not_ready' ? '本情景严格子图尚未准备好；不使用软避让代替。'
          : '对同一候选池按本情景条件重新计算道路。'}</p>
        <p>已比较 {scenario.coverage.compared} / {scenario.coverage.recalled} 个设施；未确定 {scenario.coverage.unresolved} 个。</p>
        {scenario.rows.map(row => <details key={row.asset_id}><summary>{row.name}</summary><ul>{row.conditions.map(condition =>
          <li key={condition.key}>{condition.label}：{condition.reason}<small style={{ display: 'block', overflowWrap: 'anywhere' }}>依据：{condition.evidence_refs.join('；')}</small></li>)}</ul></details>)}
        <p style={{ overflowWrap: 'anywhere' }}>路网：{String(scenario.calculation.network_id)}；图版本：{String(scenario.calculation.graph_sha256)}</p>
      </section>)}
      <p style={{ overflowWrap: 'anywhere' }}>冻结输入：{result.frozen.pool_sha256}；规则：{Object.values(result.frozen.algorithm_versions).join(' / ')}</p>
    </details><p>{result.boundary}</p>
  </section>
}

export default function CaseRoadScenarios(binding: ScenarioBinding) {
  const { user, sessionEpoch } = useAuth()
  const [open, setOpen] = useState(false)
  const identity = JSON.stringify([user?.id, sessionEpoch, user?.role, binding])
  return <details onToggle={event => setOpen(event.currentTarget.open)}><summary>比较不同条件下的依据</summary>
    <p>可按需比较资料有效期、已登记车型或额外排除入口／道路。基准自动保留，不修改真实业务记录，也不要求每案操作。</p>
    {open && <ScenarioSession key={identity} {...binding} />}
  </details>
}
export function ScenarioSession(binding: ScenarioBinding) {
  const { user, sessionEpoch } = useAuth()
  const cache = useQueryClient()
  const [selected, setSelected] = useState<string[]>([])
  const [eventId, setEventId] = useState<string | null>(null)
  const keys = ['case-road-scenarios', user?.id, sessionEpoch, user?.role, binding.artifactId, binding.artifactHash, binding.resultId, binding.resultHash]
  const options = useQuery({ queryKey: [...keys, 'options'], queryFn: ({ signal }) => readScenarioOptions(binding, signal), retry: false, staleTime: 0 })
  const result = useQuery({ queryKey: [...keys, 'job', eventId], queryFn: ({ signal }) => readScenarioJob(binding, eventId, signal), retry: false, staleTime: 0,
    refetchInterval: query => active(query.state.data?.status) ? 5000 : false })
  const submit = useMutation({ mutationFn: () => createScenarioJob(binding, selected), retry: false,
    onSuccess: data => { setEventId(data.event_id); void cache.invalidateQueries({ queryKey: keys }) } })
  const cancel = useMutation({ mutationFn: () => cancelScenarioJob(result.data!.event_id), retry: false,
    onSuccess: () => { void cache.invalidateQueries({ queryKey: keys }) } })
  const optionsOutdated = options.isError && isAxiosError(options.error) && options.error.response?.status === 409
  // A failed current permission check suppresses all formerly cached titles/counts.
  if (options.isError && !optionsOutdated || result.isError || submit.isError || cancel.isError) return <Alert type="warning" message="条件比较暂不可读或依据已变化。旧结果已隐藏，请重新打开后核对。" />
  if (options.isPending || result.isPending) return <p role="status">正在核对可比较条件和当前权限…</p>
  if (result.data?.artifact && !validScenarioResult(result.data.artifact, binding)) return <Alert type="warning" message="条件比较依据尚未确认。" />
  if (optionsOutdated) {
    // New-run eligibility is not historical read authorization. Wait for the
    // independent current-session read, never use cache to bypass that check.
    if (!result.isFetchedAfterMount || result.isFetching) return <p role="status">正在重新核对冻结历史结果的当前权限…</p>
    return <Space direction="vertical" style={{ width: '100%' }}>
      <Alert type="info" message="当前资料或规则已变化，不能发起新的条件比较。" />
      {result.data?.artifact ? <><p>以下为通过当前权限核验的冻结历史结果，不代表当前条件。</p><RoadScenarioContent result={result.data.artifact} /></>
        : <p>这份依据尚无已完成的冻结历史结果，请从最新成果发起比较。</p>}
    </Space>
  }
  if (!options.data || options.data.artifact_id !== binding.artifactId || options.data.artifact_sha256 !== binding.artifactHash) return <Alert type="warning" message="条件比较依据尚未确认。" />
  const job = result.data, busy = active(job?.status) || submit.isPending || cancel.isPending
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Tag>基准条件自动包含；最多再选两项</Tag>
    {options.data.options.length ? <fieldset disabled={busy}><legend>需要比较的已登记条件</legend>
      {options.data.options.map(option => <label key={option.id} style={{ display: 'block', marginBottom: 8 }}>
        <Checkbox checked={selected.includes(option.id)} disabled={busy || option.kind === 'extra_road_exclusion' && !option.source_retained || !selected.includes(option.id) && selected.length >= 2}
          onChange={event => setSelected(previous => toggleScenarioOption(previous, option.id, event.target.checked))}>{option.label}
          {option.kind === 'extra_road_exclusion' && !option.source_retained && '（尚缺该版本离线构图源包）'}</Checkbox>
      </label>)}</fieldset> : <p>暂无可比较的已登记条件，现有成果仍可查看。</p>}
    {options.data.road_exclusions.state === 'not_ready' && <p>{options.data.road_exclusions.reason}</p>}
    <Space><Button disabled={busy || selected.length === 0} loading={submit.isPending} onClick={() => submit.mutate()}>开始条件比较</Button>
      {active(job?.status) && <Button loading={cancel.isPending} onClick={() => cancel.mutate()}>取消本次比较</Button>}</Space>
    {active(job?.status) && <p role="status">后台比较中：已完成 {job!.progress.scenarios_completed} / {job!.progress.scenarios_total} 套条件；可离开页面，稍后继续查看。</p>}
    {job?.status === 'failed' && <Alert type="warning" message="比较服务未完成，请恢复服务后重试；不表示设施不可达。" />}
    {job?.status === 'superseded' && <Alert type="info" message="来源或授权已变化，本次比较已停止；请使用对应的新成果。" />}
    {job?.status === 'cancelled' && <p>比较已取消，真实道路状态未改变。</p>}
    {job?.artifact && <RoadScenarioContent result={job.artifact} />}
  </Space>
}
