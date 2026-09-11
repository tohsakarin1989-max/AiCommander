import { useState } from 'react'
import { Alert, Button, Empty, Select, Space, Table, Tag } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { governanceApi } from '../../services/governance'
import { evaluationStatus, evaluationMetric } from './evaluationPresentation'
import EvaluationLabelEditor from './EvaluationLabelEditor'
import EvaluationDiagnosticsPanel from './EvaluationDiagnosticsPanel'

export default function FixedEvaluationPanel() {
  const cache = useQueryClient()
  const [before, setBefore] = useState<number>()
  const [datasetId, setDatasetId] = useState<number>()
  const [policy, setPolicy] = useState<'captured' | 'current_candidate'>('captured')
  const [baseline, setBaseline] = useState<string>()
  const [candidate, setCandidate] = useState<string>()
  const [jobId, setJobId] = useState<string>()
  const [jobPage, setJobPage] = useState(1)
  const [labelsOpen, setLabelsOpen] = useState(false)
  const [diagnosticId, setDiagnosticId] = useState<string>()
  const datasets = useQuery({ queryKey: ['fixed-datasets', before], queryFn: () => governanceApi.getDatasets(before), retry: false })
  const history = useQuery({ queryKey: ['fixed-evaluations'], queryFn: governanceApi.getEvaluations, refetchInterval: 30000, retry: false })
  const roadJobs = useQuery({ queryKey: ['road-evaluation-directory', jobPage], queryFn: () => governanceApi.getRoadJobs(jobPage),
    refetchInterval: 15000, retry: false })
  const selected = datasets.data?.items.find(row => row.id === datasetId)
  const visible = !datasets.isError && !history.isError
  const records = visible ? (history.data || []).filter(row => row.dataset_id === datasetId) : []
  const refresh = () => { void cache.invalidateQueries({ queryKey: ['fixed-evaluations'] }); void cache.invalidateQueries({ queryKey: ['intelligence-runtime-overview'] }); void cache.invalidateQueries({ queryKey: ['road-evaluation-directory'] }) }
  const run = useMutation({
    mutationFn: async () => {
      if (!selected || !visible) throw new Error('dataset_unavailable')
      if (selected.kind === 'road') {
        const requestId = Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')
        const job = await governanceApi.runRoad(selected.id, requestId)
        return { jobId: job.event_id }
      }
      await governanceApi.runFixed(selected.id, policy)
      return { jobId: undefined }
    },
    retry: false,
    onSuccess: value => { setJobId(value.jobId); refresh() },
  })
  const job = useQuery({ queryKey: ['road-evaluation', jobId], queryFn: () => governanceApi.getRoadJob(jobId!),
    enabled: !!jobId, retry: false,
    refetchInterval: query => query.state.error ? false : ['pending', 'processing', 'retry'].includes(query.state.data?.status || 'pending') ? 3000 : 30000,
  })
  const cancel = useMutation({ mutationFn: (id: string) => governanceApi.cancelRoadJob(id),
    onSuccess: result => { void cache.invalidateQueries({ queryKey: ['road-evaluation', result.event_id] }); refresh() } })
  const comparison = useMutation({ mutationFn: () => governanceApi.compareFixed(baseline!, candidate!) })
  const changeDataset = (id?: number) => {
    setDatasetId(id); setBaseline(undefined); setCandidate(undefined); setJobId(undefined)
    setDiagnosticId(undefined)
    comparison.reset(); run.reset(); cancel.reset()
  }
  const compareOptions = records.filter(row => row.algorithm_manifest.evaluation_schema === 'fixed-evaluation-4.5-1')
    .map(row => ({ value: row.id, label: `${new Date(row.started_at).toLocaleString()} · ${evaluationStatus(row.status)} · ${row.id.slice(0, 8)}` }))
  const busy = run.isPending || comparison.isPending
  return <section className="fixed-evaluations" aria-labelledby="fixed-evaluation-heading">
    <header><div><h2 id="fixed-evaluation-heading">固定输入评测</h2><p>相同输入、明确版本。失败保留在样本中，未标注变化不算效果提升。</p></div>
      <Button onClick={() => { void datasets.refetch(); refresh() }}>刷新</Button></header>
    {datasets.isError || history.isError ? <Alert type="warning" showIcon message="评测数据不可用，已隐藏历史结果。请检查权限或重试。" /> : null}
    <div className="fixed-evaluations__toolbar">
      <label>已冻结的数据集<Select aria-label="已冻结的数据集" value={datasetId} loading={datasets.isFetching}
        disabled={busy || datasets.isError} placeholder="选择已有固定输入"
        options={(datasets.data?.items || []).map(row => ({ value: row.id, label: `${row.name} / ${row.version} · ${row.kind === 'road' ? '道路' : '案件'} · ${row.sample_count}份` }))}
        onChange={changeDataset} /></label>
      {selected?.kind === 'case' && <label>评分版本<Select aria-label="评分版本" value={policy} disabled={busy} onChange={setPolicy}
        options={[{ value: 'captured', label: '冻结时原版本' }, { value: 'current_candidate', label: '当前候选版本' }]} /></label>}
      <Button type="primary" loading={run.isPending} disabled={!selected || !visible || busy}
        onClick={() => { comparison.reset(); run.mutate() }}>运行评测</Button>
    </div>
    <Space wrap><Button size="small" disabled={before === undefined || busy} onClick={() => { changeDataset(); setBefore(undefined) }}>最新数据集</Button>
      <Button size="small" disabled={!datasets.data?.next_before_id || busy} onClick={() => { changeDataset(); setBefore(datasets.data!.next_before_id!) }}>更早数据集</Button></Space>
    {!datasets.isLoading && !datasets.isError && !datasets.data?.items.length && <Empty description="此页暂无可访问的固定输入。由管理员归档评测集后运行；未冻结的实时案件不替代固定评测。" />}
    {run.isError && <Alert type="error" showIcon message="评测未完成，请核对输入与版本；如网络中断，请先刷新记录，避免重复提交。" />}
    {cancel.isError && <Alert type="error" message="取消未确认，请刷新任务状态。" />}
    <div className="fixed-evaluations__comparison">
      <h3>我的道路评测任务</h3>
      <p>离开页面不会停止后台运行。可直接打开已有任务，无需重新提交。</p>
      {roadJobs.isError ? <Alert type="warning" message="任务目录暂不可用，刷新后重试。" /> : <Table size="small"
        rowKey="event_id" loading={roadJobs.isFetching} dataSource={roadJobs.data?.items || []} scroll={{ x: 540 }}
        pagination={{ current: jobPage, pageSize: 10, total: roadJobs.data?.total || 0, onChange: setJobPage, showSizeChanger: false }}
        locale={{ emptyText: '尚无本人提交的道路评测任务' }} columns={[
          { title: '提交时间', dataIndex: 'created_at', render: value => new Date(value).toLocaleString() },
          { title: '状态', dataIndex: 'status', render: evaluationStatus },
          { title: '来源', render: (_, row) => row.source_available ? '当前可访问' : '已撤权或来源变化' },
          { title: '操作', render: (_, row) => <Space wrap>
            <Button size="small" disabled={!row.source_available || roadJobs.isFetching} onClick={() => setJobId(row.event_id)}>打开任务</Button>
            {['pending', 'processing', 'retry'].includes(row.status) && <Button size="small" danger
              loading={cancel.isPending && cancel.variables === row.event_id} onClick={() => cancel.mutate(row.event_id)}>取消</Button>}
          </Space> },
        ]} />}
    </div>
    {jobId && <div aria-live="polite">
      {job.isError ? <Alert type="warning" message="道路任务不可读取，可能已撤权或来源变化；旧结果已隐藏。" /> : job.data && !job.isFetching ? <Space wrap>
        <Tag>道路评测：{evaluationStatus(job.data.status)}</Tag>
        {job.data.result_status && <span>{evaluationStatus(job.data.result_status)}，失败样本 {job.data.metrics?.failed_sample_count ?? '未知'}</span>}
        {['pending', 'processing', 'retry'].includes(job.data.status) && <Button danger loading={cancel.isPending} onClick={() => cancel.mutate(jobId)}>取消此任务</Button>}
      </Space> : <span>正在读取道路任务…</span>}
    </div>}
    {datasetId && visible && <Table size="small" rowKey="id" loading={history.isFetching} dataSource={records} pagination={{ pageSize: 8 }} scroll={{ x: 680 }}
      locale={{ emptyText: '此数据集暂无最近运行记录' }} columns={[
        { title: '运行时间', dataIndex: 'started_at', render: value => new Date(value).toLocaleString() },
        { title: '状态', dataIndex: 'status', render: evaluationStatus },
        { title: '版本方式', render: (_, row) => row.algorithm_manifest.scorer_policy === 'current_candidate' ? '当前候选' : selected?.kind === 'road' ? '固定路网' : '冻结原版本' },
        { title: '样本 / 失败 / 未标注', render: (_, row) => `${row.metrics.case_count ?? row.metrics.sample_count ?? '—'} / ${row.metrics.failed_case_count ?? row.metrics.failed_sample_count ?? '—'} / ${row.metrics.unlabeled_case_count ?? row.metrics.unlabeled_sample_count ?? '—'}` },
        { title: '已标注命中率', render: (_, row) => evaluationMetric(row.metrics.positive_top3_hit_rate) },
        { title: '操作', render: (_, row) => row.algorithm_manifest.evaluation_schema === 'road-evaluation-run-4.5-1' ? <Button size="small" onClick={() => setJobId(row.id)}>查看道路任务</Button>
          : row.algorithm_manifest.evaluation_schema === 'fixed-evaluation-4.5-1' ? <Button size="small" onClick={() => setDiagnosticId(row.id)}>错误诊断</Button> : '—' },
      ]} />}
    {diagnosticId && visible && records.some(row => row.id === diagnosticId) && <EvaluationDiagnosticsPanel key={diagnosticId} runId={diagnosticId} />}
    {selected?.kind === 'case' && visible && <div className="fixed-evaluations__comparison">
      <details onToggle={event => setLabelsOpen(event.currentTarget.open)}><summary>人工标签与版本修订</summary>
        {labelsOpen && <EvaluationLabelEditor key={selected.id} datasetId={selected.id} />}
      </details>
      <h3>同一数据集的两次运行比较</h3>
      <Space wrap><Select aria-label="基线运行" placeholder="基线运行" value={baseline} options={compareOptions} disabled={busy} onChange={value => { setBaseline(value); comparison.reset() }} />
        <Select aria-label="候选运行" placeholder="候选运行" value={candidate} options={compareOptions} disabled={busy} onChange={value => { setCandidate(value); comparison.reset() }} />
        <Button disabled={!baseline || !candidate || baseline === candidate || busy} loading={comparison.isPending} onClick={() => comparison.mutate()}>比较结果</Button></Space>
      {comparison.isError && <Alert type="warning" message="无法比较：请确认输入、标签、版本和当前权限一致。" />}
      {comparison.data && !comparison.isError && !history.isFetching && records.some(row => row.id === baseline) && records.some(row => row.id === candidate) && <div aria-live="polite"><p>{comparison.data.mode === 'repeatability' ? '同代码重复性检查，不代表算法升级。' : '不同代码版本的固定输入比较。'}</p>
        <Space wrap><Tag>改善 {comparison.data.counts.improved}</Tag><Tag>退步 {comparison.data.counts.regressed}</Tag>
          <Tag>未标注变化 {comparison.data.counts.unlabeled_changed}</Tag><span>失败：基线 {comparison.data.baseline_failed_cases}，候选 {comparison.data.candidate_failed_cases}</span></Space>
        <p>{comparison.data.boundary}</p></div>}
    </div>}
  </section>
}
