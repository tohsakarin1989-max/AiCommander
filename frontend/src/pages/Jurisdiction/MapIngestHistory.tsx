import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Input, Pagination, Select, Space, Table } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { mapLedgerImportsApi, type MapFieldContract, type MapFieldGroup, type MapLedgerClaim, type MapLedgerPreview, type MapLedgerRun, type MapRetryRequest, type MapRowClassification } from '../../services/mapLedgerImports'
import { displayMapValue, downloadMapFile, groupLabels, mapBatchError, mapImportError, mapPreviewCanCommit, mapReceivedTime, mapRowLabels, prepareMapRetry } from './mapLedgerPresentation'
import MapImportPlan, { MapPlanDetails } from './MapImportPlan'
import MapFieldDecision from './MapFieldDecision'
import MapBatchCorrection from './MapBatchCorrection'
import MapLedgerComparisonReceipt from './MapLedgerComparison'
import { ledgerJobLabels } from './MapLedgerJobs'

export default function MapIngestHistory({ sourceId, contract, templateId, onChanged, onDirtyChange }: {
  sourceId: number; contract: MapFieldContract; templateId?: number; onChanged: () => void; onDirtyChange: (dirty: boolean) => void
}) {
  const { user, sessionEpoch } = useAuth(), queryClient = useQueryClient()
  const [offset, setOffset] = useState(0), [claimOffset, setClaimOffset] = useState(0)
  const [run, setRun] = useState<MapLedgerRun | null>(null), [classification, setClassification] = useState<MapRowClassification>()
  const [claim, setClaim] = useState<MapLedgerClaim | null>(null), [values, setValues] = useState<Record<string, unknown>>({})
  const [preview, setPreview] = useState<MapLedgerPreview | null>(null), [attempt, setAttempt] = useState<MapRetryRequest | null>(null)
  const [busy, setBusy] = useState(false), [failure, setFailure] = useState(''), [notice, setNotice] = useState('')
  const [submissionSent, setSubmissionSent] = useState(false)
  const [decision, setDecision] = useState<{ claimId: number; group: MapFieldGroup } | null>(null)
  const [batchRows, setBatchRows] = useState<MapLedgerClaim[]>([]), [batchLocked, setBatchLocked] = useState(false)
  const mounted = useRef(true), busyRef = useRef(false)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const runs = useQuery({ queryKey: ['map-ingest-runs', user?.id, sessionEpoch, sourceId, offset], gcTime: 0,
    queryFn: ({ signal }) => mapLedgerImportsApi.runs(sourceId, offset, signal) })
  const claims = useQuery({ queryKey: ['map-ingest-claims', user?.id, sessionEpoch, run?.id, claimOffset, classification], gcTime: 0,
    queryFn: ({ signal }) => mapLedgerImportsApi.claims(run!.id, claimOffset, classification, signal), enabled: !!run })
  const dirty = claim !== null || decision !== null || batchRows.length > 0
  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false) }, [dirty, onDirtyChange])
  useEffect(() => {
    if (!dirty) return
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', guard); return () => window.removeEventListener('beforeunload', guard)
  }, [dirty])
  useEffect(() => {
    if (batchLocked || !claims.isSuccess) return
    setBatchRows(previous => {
      const current = new Map(claims.data.items.map(row => [row.id, row]))
      const cause = previous.length ? mapBatchError(previous[0])?.key : undefined
      return previous.map(row => current.get(row.id) || row).filter(row => !!cause && mapBatchError(row)?.key === cause)
    })
  }, [claims.data, claims.isSuccess, batchLocked])
  const selectBatchRows = (keys: React.Key[]) => {
    if (batchLocked || busy || claim || decision || attempt || !run) return
    const available = new Map([...batchRows, ...(claims.isSuccess ? claims.data.items : [])].map(row => [row.id, row]))
    const selected = keys.map(key => available.get(Number(key))).filter((row): row is MapLedgerClaim => !!row)
    const cause = selected.length ? mapBatchError(selected[0])?.key : undefined
    if (selected.length > 200 || selected.some(row => row.run_id !== run.id || !cause || mapBatchError(row)?.key !== cause)) {
      setFailure('请选择同批次、同一字段和错误的未修订失败行，每次最多 200 行。'); return
    }
    setBatchRows(selected); setFailure(''); setNotice('')
  }
  const allowReplace = () => !decision && (!claim || (!attempt && window.confirm('当前异常行有尚未提交的修正，切换后会丢失。仍要切换吗？')))
  const act = async (work: () => Promise<void>) => {
    if (busyRef.current) return
    busyRef.current = true; setBusy(true); setFailure(''); setNotice('')
    try { await work() } catch (error) {
      if (mounted.current) setFailure(`${mapImportError(error).message}。修正输入和原请求仍保留，请核对批次；不要重新导入成功行。`)
    } finally { busyRef.current = false; if (mounted.current) setBusy(false) }
  }
  const plan = () => act(async () => {
    if (!run || !claim) return
    const payload = prepareMapRetry(claim.id, values, templateId)
    const result = await mapLedgerImportsApi.retryPreview(run.id, payload)
    if (mounted.current) { setPreview(result); setAttempt({ ...payload, plan_token: result.plan_token }) }
  })
  const retry = () => act(async () => {
    if (!run || !attempt || !mapPreviewCanCommit(preview)) return
    setSubmissionSent(true)
    let result: MapLedgerRun
    try { result = await mapLedgerImportsApi.retry(run.id, attempt) } catch (error) {
      const { code } = mapImportError(error)
      if (mounted.current && ['plan_stale', 'template_drift', 'retry_identifier_taken', 'retry_parent_stale', 'retry_row_superseded', 'retry_successful_row_forbidden'].includes(code || '')) {
        setSubmissionSent(false); setAttempt(null); setPreview(null)
      }
      throw error
    }
    if (!mounted.current) return
    setNotice(`修正已记录为新批次 ${result.id}，原始行未覆盖。`)
    setClaim(null); setValues({}); setPreview(null); setAttempt(null); setSubmissionSent(false)
    void queryClient.invalidateQueries({ queryKey: ['map-ingest-runs'] })
    void queryClient.invalidateQueries({ queryKey: ['map-ingest-claims'] })
    onChanged()
  })
  return <section aria-label="生产台账最近批次与异常续做">
    <h4>最近导入批次</h4>
    {runs.isError && <Alert type="error" message="批次读取失败，未展示旧缓存。" action={<Button onClick={() => void runs.refetch()}>重试</Button>} />}
    <Table size="small" rowKey="id" loading={runs.isPending} dataSource={runs.isSuccess ? runs.data.items : []} pagination={false} columns={[
      { title: '原文件 / 来源修订', render: (_, item) => <span>{item.filename}<br />{item.source_revision || '未单列修订'}<br />接收：{mapReceivedTime(item.started_at)}</span> },
      { title: '处理结果', render: (_, item) => <>{ledgerJobLabels[item.status] || item.status}<br />{Object.entries(mapRowLabels).map(([key, label]) => `${label} ${item.counts?.[key as MapRowClassification] ?? '未记录'}`).join(' · ')}</> },
      { title: '批次', render: (_, item) => <Button disabled={busy || !!attempt || !!decision || batchRows.length > 0} onClick={() => {
        if (!allowReplace()) return
        setRun(item); setClaim(null); setValues({}); setPreview(null); setAttempt(null); setClaimOffset(0); setFailure('')
      }}>查看逐行回执</Button> },
    ]} />
    <Pagination size="small" current={offset / 10 + 1} pageSize={10} total={runs.isSuccess ? runs.data.total : 0} showSizeChanger={false} onChange={page => setOffset((page - 1) * 10)} />
    {run && <>
      <p>批次 <code>{run.id}</code> · 工作表 {run.table_metadata?.sheet_name || 'CSV / 未单列'} · 表头行 {run.table_metadata?.header_row ?? '未记录'} · 来源修订 {run.source_revision || '未记录'}</p>
      {run.parent_run_id && <p>本次修正来源批次：{run.parent_run_id}</p>}
      {run.ledger_declaration && <p>完整度与期间声明人：{run.declaration_actor_id ? `账号 #${run.declaration_actor_id}` : '历史记录未保存'}，声明时间为本批次接收时间；业务有效期另行标明。</p>}
      <MapLedgerComparisonReceipt key={run.id} runId={run.id} declaration={run.ledger_declaration} />
      <p>原件引用：{run.original_evidence_object_id ? `#${run.original_evidence_object_id}` : '此批次未记录受控原件引用'}。下载仍按现有原件权限，不以本页字段代替原件。</p>
      {run.original_evidence_object_id && user?.role === 'admin' && <Button disabled={busy} onClick={() => void act(async () => {
        const blob = await mapLedgerImportsApi.original(run.id)
        if (mounted.current) downloadMapFile(blob, run.filename)
      })}>下载本批次受控原件</Button>}
      <Select aria-label="台账回执行分类" allowClear placeholder="全部行分类" value={classification} disabled={busy || !!attempt || !!decision || batchRows.length > 0} style={{ minWidth: 180 }}
        options={Object.entries(mapRowLabels).map(([value, label]) => ({ value, label }))}
        onChange={value => { setClassification(value); setClaimOffset(0) }} />
      <Button disabled={busy || batchLocked} onClick={() => {
        void claims.refetch(); void runs.refetch(); void queryClient.invalidateQueries({ queryKey: ['map-ledger-comparison'] })
      }}>刷新回执</Button>
      <p>勾选同因失败行可一起修正，跨页保留选择，最多 200 行。成功行、已有修订行及身份或来源冲突不可批量选择。</p>
      {batchRows.length > 0 && <Button disabled={busy || batchLocked || !claims.isSuccess} onClick={() => {
        const cause = mapBatchError(batchRows[0])?.key
        selectBatchRows([...new Set([...batchRows.map(row => row.id), ...(claims.isSuccess ? claims.data.items : [])
          .filter(row => !!cause && mapBatchError(row)?.key === cause).map(row => row.id)])])
      }}>选中本页同因异常</Button>}
      {claims.isError && <Alert type="error" message="行回执读取失败，当前页不使用旧缓存。" />}
      <Table size="small" rowKey="id" loading={claims.isPending} dataSource={claims.isSuccess ? claims.data.items : []} pagination={false}
        rowSelection={{ selectedRowKeys: batchRows.map(row => row.id), preserveSelectedRowKeys: true, hideSelectAll: true,
          onChange: selectBatchRows, getCheckboxProps: item => ({ disabled: busy || batchLocked || !!claim || !!attempt || !!decision
            || item.status === 'staged' || !mapBatchError(item) || (batchRows.length > 0 && mapBatchError(item)?.key !== mapBatchError(batchRows[0])?.key),
          'aria-label': `选择第 ${item.row_number} 行同因异常` }) }}
        expandable={{ expandedRowRender: item => <><p>原始列值：{displayMapValue(item.raw_payload)}</p><p>原声明 {item.parent_claim_id ?? '无'} · 身份引用 {item.source_identity_id ?? '未确定'} · 身份裁决 {item.identity_decision_id ?? '未记录'}</p>{item.plan && <MapPlanDetails row={item.plan} fields={contract.fields} />}</> }} columns={[
          { title: '原表行', dataIndex: 'row_number' }, { title: '状态', render: (_, item) => item.retry_superseded ? '已有后续修订，请查看最新批次' : mapRowLabels[item.plan?.classification as MapRowClassification] || item.status },
          { title: '异常续做', render: (_, item) => <Space wrap><Button disabled={busy || !!attempt || !!decision || batchRows.length > 0 || item.status === 'staged' || item.retry_superseded || !['failed', 'conflict', 'identity_pending'].includes(item.plan?.classification || '') || !item.raw_payload}
            onClick={() => { if (!allowReplace()) return; setClaim(item); setValues({ ...item.raw_payload }); setPreview(null); setAttempt(null); setFailure(''); setNotice('') }}>修正这一行</Button>
            {item.plan?.groups.filter(group => group.status === 'conflict' && ['geometry', 'water_cut', 'production', 'details'].includes(group.group)).map(group => <Button key={group.group}
              disabled={busy || !!attempt || !!decision || batchRows.length > 0 || item.status === 'staged' || item.retry_superseded} onClick={() => {
                if (!allowReplace()) return
                setClaim(null); setValues({}); setDecision({ claimId: item.id, group: group.group as MapFieldGroup }); setNotice('')
              }}>核对{groupLabels[group.group] || group.group}来源</Button>)}
          </Space> },
        ]} />
      <Pagination size="small" current={claimOffset / 20 + 1} pageSize={20} total={claims.isSuccess ? claims.data.total : 0} showSizeChanger={false} onChange={page => setClaimOffset((page - 1) * 20)} />
    </>}
    {notice && <Alert type="success" showIcon message={notice} />}
    {failure && <Alert type="warning" showIcon role="alert" message={failure} />}
    {run && batchRows.length > 0 && <MapBatchCorrection key={`${sessionEpoch}:${sourceId}:${run.id}`} run={run} claims={batchRows}
      templateId={templateId} fields={contract.fields} onLockedChange={setBatchLocked} onClose={() => { setBatchRows([]); setBatchLocked(false) }}
      onComplete={result => {
        setBatchRows([]); setBatchLocked(false); setRun(result); setClassification(undefined); setClaimOffset(0)
        setNotice(`所选行修正已记录为新批次 ${result.id}，下方回执可逐行核对；原始行未覆盖。`)
        void queryClient.invalidateQueries({ queryKey: ['map-ingest-runs'] }); void queryClient.invalidateQueries({ queryKey: ['map-ingest-claims'] }); onChanged()
      }} />}
    {decision && <MapFieldDecision key={`${decision.claimId}:${decision.group}`} {...decision} fields={contract.fields}
      onClose={() => setDecision(null)} onComplete={id => {
        setDecision(null); setNotice(`已按明确理由采用字段组，新批次 ${id}；原始行和其他字段组未覆盖。`)
        void queryClient.invalidateQueries({ queryKey: ['map-ingest-runs'] }); void queryClient.invalidateQueries({ queryKey: ['map-ingest-claims'] }); onChanged()
      }} />}
    {claim && <div>
      <h4>第 {claim.row_number} 行修正，保留原列名</h4>
      <p>完整原列值提交为新声明，不覆盖旧行。使用{templateId ? `当前所选模板 #${templateId}` : '原批次模板'}；变更模板后须重新预览。</p>
      {Object.entries(values).map(([key, value]) => <label key={key} style={{ display: 'block', margin: '8px 0' }}>{key}<Input
        aria-label={`修正台账列 ${key}`} value={value == null ? '' : String(value)} disabled={busy || !!attempt}
        onChange={event => { setValues(previous => ({ ...previous, [key]: event.target.value })); setPreview(null) }} /></label>)}
      <Space wrap><Button disabled={busy || !!attempt} onClick={() => void plan()}>预览此行修正</Button>
        <Button disabled={busy || !mapPreviewCanCommit(preview)} onClick={() => void retry()}>按原请求提交此行修正</Button>
        <Button disabled={busy || submissionSent} onClick={() => {
          setAttempt(null); setPreview(null)
        }}>核对后返回修改</Button>
        <Button disabled={busy || submissionSent} onClick={() => {
          if (!window.confirm('放弃这条异常行尚未提交的修正？原批次记录不会改变。')) return
          setClaim(null); setValues({}); setAttempt(null); setPreview(null); setFailure('')
        }}>放弃本页修正</Button></Space>
      {submissionSent && <p>本次提交结果尚待确认，只能使用上面冻结的原请求重试。不能更改内容或换凭证；刷新回执不会清除本页修正。</p>}
      {attempt && <p>修正凭证：{attempt.request_id}。确认前保持同一请求；失败重试不会改写输入。可为仍未编号的原设施补充编号；已有设施合并仍使用设施身份原入口，本页不按名称猜测合并。</p>}
      {preview && <MapImportPlan preview={preview} fields={contract.fields} />}
    </div>}
  </section>
}
