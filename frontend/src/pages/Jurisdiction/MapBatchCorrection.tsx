import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Select, Space, Table } from 'antd'
import { mapLedgerImportsApi, type MapImportField, type MapLedgerClaim, type MapLedgerPreview, type MapLedgerRun, type MapRetryRequest } from '../../services/mapLedgerImports'
import { displayMapValue, mapBatchError, mapBatchNumericColumns, mapBatchPreviewCanCommit, mapImportError, prepareMapBatchRetry, type MapBatchChange } from './mapLedgerPresentation'
import MapImportPlan from './MapImportPlan'

export default function MapBatchCorrection({ run, claims, templateId, fields, onLockedChange, onComplete, onClose }: {
  run: MapLedgerRun; claims: MapLedgerClaim[]; templateId?: number; fields: MapImportField[]
  onLockedChange: (locked: boolean) => void; onComplete: (result: MapLedgerRun) => void; onClose: () => void
}) {
  const [change, setChange] = useState<MapBatchChange>({ kind: 'template' })
  const [attempt, setAttempt] = useState<MapRetryRequest | null>(null), [preview, setPreview] = useState<MapLedgerPreview | null>(null)
  const [busy, setBusy] = useState(false), [failure, setFailure] = useState(''), [confirmed, setConfirmed] = useState(false)
  const [submissionSent, setSubmissionSent] = useState(false)
  const mounted = useRef(true), busyRef = useRef(false), attemptRef = useRef<MapRetryRequest | null>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const columns = mapBatchNumericColumns(run, claims[0]).filter(column => claims.every(claim => mapBatchNumericColumns(run, claim).includes(column)))
  const freeze = (request: MapRetryRequest | null) => { attemptRef.current = request; setAttempt(request); onLockedChange(!!request) }
  const act = async (work: () => Promise<void>) => {
    if (busyRef.current) return
    busyRef.current = true; setBusy(true); setFailure(''); onLockedChange(true)
    try { await work() } catch (error) {
      if (mounted.current) setFailure(`${mapImportError(error).message}。所选行和修正输入仍保留。`)
    } finally {
      busyRef.current = false
      if (mounted.current) { setBusy(false); onLockedChange(!!attemptRef.current) }
    }
  }
  const inspect = () => act(async () => {
    const request = attemptRef.current || prepareMapBatchRetry(run, claims, change, templateId)
    freeze(request); setPreview(null); setConfirmed(false)
    const result = await mapLedgerImportsApi.retryPreview(run.id, request)
    if (!mounted.current) return
    freeze({ ...request, plan_token: result.plan_token }); setPreview(result)
  })
  const submit = () => act(async () => {
    if (!attemptRef.current || !confirmed || !mapBatchPreviewCanCommit(preview, claims)) return
    setSubmissionSent(true)
    try {
      const result = await mapLedgerImportsApi.retry(run.id, attemptRef.current)
      if (mounted.current) { attemptRef.current = null; onComplete(result) }
    } catch (error) {
      const { code } = mapImportError(error)
      if (mounted.current && ['plan_stale', 'template_drift', 'retry_identifier_taken', 'retry_parent_stale',
        'retry_row_superseded', 'retry_successful_row_forbidden'].includes(code || '')) {
        freeze(null); setPreview(null); setConfirmed(false); setSubmissionSent(false)
      }
      throw error
    }
  })
  const label = (field: string) => fields.find(item => item.key === field)?.label || field
  const changes = claims.map(claim => ({ ...claim, corrected: attempt?.rows.find(row => row.claim_id === claim.id)?.values }))
  const canCommit = mapBatchPreviewCanCommit(preview, claims)
  return <section aria-label="同因台账异常批量修正">
    <h4>同因异常：已选 {claims.length} 行，最多 200 行</h4>
    <p>同一批次 {run.id}，同一来源 #{run.source_id}，原模板 #{run.template_id}。仅处理{label(mapBatchError(claims[0])?.field || '')}：{mapBatchError(claims[0])?.message}</p>
    <p>先选择同一种修正方式，再逐行预览。编号、名称、产量等业务事实不统一填值；身份及来源冲突仍逐项核对。</p>
    <Select aria-label="同因异常修正方式" value={change.kind} disabled={busy || !!attempt} style={{ minWidth: 280 }} options={[
      { value: 'template', label: '套用明确修正后的新模板' },
      { value: 'numeric_format', label: '整理指定数字列的空白与全角格式', disabled: !columns.length },
    ]} onChange={kind => { setChange(kind === 'template' ? { kind } : { kind, column: columns[0] }); setPreview(null); setConfirmed(false) }} />
    {change.kind === 'template' ? <p>本次使用{templateId ? `所选模板 #${templateId}` : '尚未选择新模板'}，不改变原列值。请先在上方保存并选择来源已确认的字段映射、单位或坐标系模板，再选行；不从数值猜测坐标系。</p>
      : <>
        <Select aria-label="批量整理数字列" value={change.column} disabled={busy || !!attempt} style={{ minWidth: 180 }}
          options={columns.map(column => ({ value: column, label: column }))} onChange={column => setChange({ kind: 'numeric_format', column })} />
        <p>沿用原批次模板 #{run.template_id}。只去除首尾空白、转换全角数字和小数点；不换算单位、不删除分隔符、不将空白变成零。</p>
      </>}
    <Table size="small" rowKey="id" dataSource={changes} pagination={{ pageSize: 20, showSizeChanger: false }} columns={[
      { title: '原表行 / 声明', render: (_, row) => `${row.row_number} / #${row.id}` },
      { title: '来源编号', render: (_, row) => row.source_record_id || '未记录' },
      { title: '修正内容', render: (_, row) => !row.corrected ? '预览后逐行核对' : change.kind === 'template'
        ? `原列值保留，模板 #${run.template_id} → #${attempt?.template_id}；采用差异见下表`
        : `${change.column}：${displayMapValue(row.raw_payload?.[change.column])} → ${displayMapValue(row.corrected[change.column])}` },
    ]} />
    {failure && <Alert type="warning" showIcon message={failure} />}
    <Space wrap>
      <Button disabled={busy || !!preview || submissionSent} loading={busy} onClick={() => void inspect()}>预览所选行修正</Button>
      <Button disabled={busy || submissionSent} onClick={() => { freeze(null); setPreview(null); setConfirmed(false); setFailure('') }}>返回修改批量方案</Button>
      <Button disabled={busy || submissionSent} onClick={() => {
        if (window.confirm('放弃本次尚未提交的批量修正？原批次记录不会改变。')) { freeze(null); onClose() }
      }}>清空批量选择</Button>
    </Space>
    {attempt && <p>修正凭证：{attempt.request_id}。原行、模板和请求已冻结；网络失败继续使用原请求，不能重新导入成功行。</p>}
    {preview && <>
      <MapImportPlan preview={preview} fields={fields} />
      {!canCommit && <Alert type="warning" message="尚有失败、身份待对应、事实冲突或预览不完整，本批不能直接写入。返回修改或缩小选择后重新预览。" />}
      <Checkbox disabled={busy || submissionSent || !canCommit} checked={confirmed} onChange={event => setConfirmed(event.target.checked)}>
        我已逐行核对以上原行、修正方式与采用差异，确认只处理同因问题
      </Checkbox>
      <Button type="primary" disabled={busy || !confirmed || !canCommit} onClick={() => void submit()}>
        {submissionSent ? '按冻结原请求核对重试' : '确认提交所选行修正'}
      </Button>
    </>}
    {submissionSent && <p>提交结果尚未确认，请按冻结原请求重试；不能改内容或清空选择。逐行结果将记录在新的修正批次，原始行保留。</p>}
  </section>
}
