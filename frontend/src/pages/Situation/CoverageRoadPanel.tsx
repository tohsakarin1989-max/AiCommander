import { useState } from 'react'
import { Button, InputNumber, Pagination, Select } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { coverageRoadApi } from '../../services/spatialCoverage'

const ACTIVE = ['pending', 'retry', 'processing']
const LABELS: Record<string, string> = { pending: '排队中', retry: '等待重试', processing: '道路计算中',
  completed: '道路计算结束', failed: '计算失败', cancelled: '已取消', superseded: '输入版本已失效' }

export default function CoverageRoadPanel({ comparisonId }: { comparisonId: string }) {
  const client = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
  const [kind, setKind] = useState<'auto' | 'truck'>('auto')
  const [height, setHeight] = useState<number | null>(null)
  const [weight, setWeight] = useState<number | null>(null)
  const [budget, setBudget] = useState<number | null>(3000)
  const [changed, setChanged] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyPage, setHistoryPage] = useState(1)
  const history = useQuery({ queryKey: ['coverage-road-history', comparisonId, historyPage],
    queryFn: () => coverageRoadApi.list(comparisonId, historyPage), enabled: historyOpen, retry: false })
  const query = useQuery({
    queryKey: ['coverage-road-job', jobId], enabled: jobId !== null,
    queryFn: () => coverageRoadApi.get(jobId!), retry: false,
    refetchInterval: state => state.state.error ? false : ACTIVE.includes(state.state.data?.status ?? 'pending') ? 5000 : 60000,
  })
  const start = useMutation({
    mutationFn: () => coverageRoadApi.start(comparisonId, budget!, kind === 'auto' ? { kind }
      : { kind, height_m: height!, weight_t: weight! }),
    onMutate: () => { setJobId(null); setChanged(false) },
    onSuccess: result => { setJobId(result.event_id); void client.invalidateQueries({ queryKey: ['coverage-road-job', result.event_id] })
      void client.invalidateQueries({ queryKey: ['coverage-road-history', comparisonId] }) },
  })
  const cancel = useMutation({
    mutationFn: (id: string) => coverageRoadApi.cancel(id),
    onSuccess: (result, id) => {
      client.setQueryData(['coverage-road-job', id], { event_id: id, status: result.status, artifact: null })
      void client.invalidateQueries({ queryKey: ['coverage-road-job', id] })
      void client.invalidateQueries({ queryKey: ['coverage-road-history', comparisonId] })
    },
  })
  const data = query.isError || query.isFetching || start.isPending ? undefined : query.data
  const active = start.isPending || (jobId !== null && (query.isPending || ACTIVE.includes(data?.status ?? '')))
  const invalid = budget === null || budget <= 0 || budget > 50000 || (kind === 'truck' && (!height || !weight))
  return <details className="sw-coverage-roads"><summary>机动车道路关联</summary>
    <p>使用登记机动车参考出发点，计算至井点附近道路的关联。不把设备位置视为实际驻车点，也不确认井场入口。</p>
    <details onToggle={event => setHistoryOpen(event.currentTarget.open)}><summary>找回已提交的道路任务</summary>
      <p>这里只列本人任务。打开结果会重新检查许可与版本；无需再次提交计算。</p>
      {history.isFetching ? <p role="status">正在读取任务目录…</p> : history.isError ? <p role="alert">任务目录暂不可读，未显示缓存目录。</p>
        : history.data && <>
          {history.data.items.length === 0 ? <p>此方案尚无本人提交的道路任务。</p>
            : <ul>{history.data.items.map(item => <li key={item.event_id}><Button onClick={() => {
              setJobId(item.event_id); setChanged(true)
              void client.invalidateQueries({ queryKey: ['coverage-road-job', item.event_id] })
            }}>{item.created_at} · {LABELS[item.status] ?? '状态待核'} · {item.event_id.slice(0, 8)}</Button></li>)}</ul>}
          <Pagination current={historyPage} pageSize={10} total={history.data.total} showSizeChanger={false} onChange={setHistoryPage} />
        </>}
      <Button disabled={history.isFetching} onClick={() => void history.refetch()}>刷新任务目录</Button>
    </details>
    <div className="sw-coverage-controls">
      <label>参考车型<Select aria-label="道路参考车型" value={kind} disabled={active}
        options={[{ value: 'auto', label: '参考小型机动车' }, { value: 'truck', label: '参考货车（需尺寸与重量）' }]}
        onChange={value => { setKind(value); setChanged(true) }} /></label>
      <label>道路距离预算（米）<InputNumber aria-label="道路距离预算" value={budget} min={1} max={50000} disabled={active}
        onChange={value => { setBudget(value); setChanged(true) }} /></label>
      {kind === 'truck' && <><label>参考车高（米）<InputNumber aria-label="参考车高" value={height} min={0.1} disabled={active}
        onChange={value => { setHeight(value); setChanged(true) }} /></label>
        <label>参考总重（吨）<InputNumber aria-label="参考总重" value={weight} min={0.1} disabled={active}
          onChange={value => { setWeight(value); setChanged(true) }} /></label></>}
    </div>
    <div className="sw-coverage-road-actions"><Button disabled={active || invalid} onClick={() => start.mutate()}>提交道路计算</Button>
      {jobId && <Button disabled={cancel.isPending || !ACTIVE.includes(data?.status ?? '')} onClick={() => cancel.mutate(jobId)}>取消道路计算</Button>}
      {jobId && <Button disabled={query.isFetching} onClick={() => void query.refetch()}>刷新道路状态</Button>}</div>
    {start.isPending && <p role="status">正在提交后台任务…</p>}
    {start.isError && <p role="alert">未能提交。请检查方案来源、车型与授权路网配置，未使用直线距离替代。</p>}
    {query.isError && <p role="alert">任务读取失败或权限已失效，旧道路成果已隐藏。</p>}
    {cancel.isError && <p role="alert">取消未确认，请刷新状态后重试。</p>}
    {data && <p role="status">{LABELS[data.status] ?? '状态待核'}{changed ? '。表单条件已调整，以下仍为原任务结果。' : ''}</p>}
    {data?.artifact && <>
      <p>{data.artifact.boundary}</p>
      <p>本任务道路预算：{data.artifact.distance_budget_m} 米。</p>
      {data.artifact.information_gaps.map((gap, index) => <p key={index}>{gap}</p>)}
      {data.artifact.state === 'calculated_reference' && <div className="sw-coverage-table"><table>
        <caption>预算内参考出发点数量，不是实际可用车辆数</caption>
        <thead><tr><th scope="col">登记井</th><th scope="col">基准</th><th scope="col">方案</th><th scope="col">接路缺口</th></tr></thead>
        <tbody>{data.artifact.targets.map(row => <tr key={row.target_id}><th scope="row">井点 {row.target_id}</th>
          <td>{row.baseline_origin_ids_within_budget.length}</td><td>{row.scenario_origin_ids_within_budget.length}</td>
          <td>{row.scenario_connection_unknown ? '移动点待核' : '仍需核验入口'}</td></tr>)}</tbody>
      </table></div>}
      <p className="sw-coverage-digest">路网版本：{data.artifact.network_id ?? '未计算'}；{data.artifact.graph_sha256 ?? ''}</p>
    </>}
  </details>
}
