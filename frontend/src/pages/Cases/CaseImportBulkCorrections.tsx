import { useEffect, useState } from 'react'
import { Alert, Button, Select } from 'antd'
import { caseImportsApi, type FailedImportRow, type ImportCorrectionResult } from '../../services/caseImports'
import { importFieldLabels } from './importCorrection'
import { assertBulkRevisions, buildBulkFormatCorrections, type BulkFormatRow, type FormatCorrection } from './importBulkCorrection'

export default function CaseImportBulkCorrections({ batchId, rows, disabled, onCorrected, onBusyChange, onDirtyChange, refresh }: {
  batchId: string; rows: FailedImportRow[]; disabled: boolean; onCorrected: (result: ImportCorrectionResult) => void
  onBusyChange: (busy: boolean) => void; onDirtyChange: (dirty: boolean) => void; refresh: () => Promise<unknown>
}) {
  const [errorGroup, setErrorGroup] = useState('')
  const [selected, setSelected] = useState<number[]>([])
  const [field, setField] = useState('')
  const [rule, setRule] = useState<FormatCorrection>('trim')
  const [plan, setPlan] = useState<BulkFormatRow[]>([])
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  const [notice, setNotice] = useState('')
  const [mustRefresh, setMustRefresh] = useState(false)
  useEffect(() => { onBusyChange(busy); return () => onBusyChange(false) }, [busy, onBusyChange])
  useEffect(() => { onDirtyChange(plan.length > 0); return () => onDirtyChange(false) }, [plan.length, onDirtyChange])
  const group = rows.filter(row => row.status === 'failed' && row.error === errorGroup)
  const fields = [...new Set(group.flatMap(row => Object.keys(row.values)))]
  const clearPreview = () => { setPlan([]); setConfirmed(false); setNotice('') }
  const submit = async () => {
    if (busy || disabled || mustRefresh || !confirmed || !plan.length) return
    setBusy(true); setFailure('')
    try {
      const latest = await caseImportsApi.getRows(batchId)
      assertBulkRevisions(plan, latest.rows)
      const result = await caseImportsApi.correctMany(batchId, plan.map(({ row, revision, changes }) => ({ row, revision, changes })))
      onCorrected(result); setPlan([]); setConfirmed(false)
      setNotice(`本次已新增 ${result.created} 条案件；其余失败原因请查看回执。成功记录未重复处理。`)
      await refresh()
    } catch (error) {
      setMustRefresh(true)
      setFailure(`${error instanceof Error ? error.message : '批量修正结果未确认'}。预览仍保留，请先刷新回执核对，不自动重试。`)
    } finally { setBusy(false) }
  }
  return <details><summary>同类格式问题成组处理</summary>
    <p>限本批次、相同失败原因。只整理首尾空白或数值全角格式；事实冲突仍逐行核对。</p>
    <Select aria-label="批量失败原因" placeholder="选择相同失败原因" value={errorGroup || undefined} disabled={disabled || busy || mustRefresh} style={{ width: '100%' }}
      options={[...new Set(rows.filter(row => row.status === 'failed').map(row => row.error).filter(Boolean))].map(error => ({ value: error, label: error }))}
      onChange={value => { setErrorGroup(value); setSelected(rows.filter(row => row.status === 'failed' && row.error === value).map(row => row.row)); setField(''); clearPreview() }} />
    <Select aria-label="批量影响行" mode="multiple" value={selected} disabled={disabled || busy || mustRefresh} style={{ width: '100%', marginTop: 8 }}
      options={group.map(row => ({ value: row.row, label: `第 ${row.row} 行 · 版本 ${row.revision}` }))}
      onChange={value => { setSelected(value); clearPreview() }} />
    <Select aria-label="批量整理字段" placeholder="选择字段" value={field || undefined} disabled={disabled || busy || mustRefresh} style={{ minWidth: 160, marginTop: 8 }}
      options={fields.map(value => ({ value, label: importFieldLabels[value] || value }))} onChange={value => { setField(value); clearPreview() }} />
    <Select aria-label="格式整理方法" value={rule} disabled={disabled || busy || mustRefresh} style={{ minWidth: 180 }}
      options={[{ value: 'trim', label: '清理首尾空白' }, { value: 'numeric_width', label: '数值全角转半角' }]}
      onChange={value => { setRule(value); clearPreview() }} />
    <Button disabled={disabled || busy || mustRefresh || !field || !selected.length} onClick={() => {
      try { const result = buildBulkFormatCorrections(rows, selected, errorGroup, field, rule); setPlan(result); setConfirmed(false); setFailure(''); setNotice(result.length ? `仅以下 ${result.length} 行发生格式变化；未变化行不提交。` : '没有可安全整理的格式变化，不提交。') }
      catch (error) { setFailure(error instanceof Error ? error.message : '无法形成预览') }
    }}>预览影响行</Button>
    {notice && <Alert type="info" message={notice} />}
    {failure && <Alert type="warning" message={failure} />}
    {plan.length > 0 && <><table className="data"><thead><tr><th>源行／版本</th><th>原值</th><th>整理后</th></tr></thead>
      <tbody>{plan.map(item => <tr key={item.row}><td>{item.row} / {item.revision}</td><td><code>{JSON.stringify(item.previous)}</code></td><td><code>{JSON.stringify(Object.values(item.changes)[0])}</code></td></tr>)}</tbody></table>
      <label><input type="checkbox" checked={confirmed} disabled={disabled || busy || mustRefresh} onChange={event => setConfirmed(event.target.checked)} />已核对影响行，仅整理格式，不改变业务事实</label>
      <Button type="primary" loading={busy} disabled={disabled || mustRefresh || !confirmed} onClick={() => void submit()}>仅重试预览中的失败行</Button>
      <Button disabled={busy || mustRefresh} onClick={clearPreview}>放弃本次预览</Button>
    </>}
    {mustRefresh && <Button disabled={busy} onClick={async () => { setBusy(true); try { await refresh(); setMustRefresh(false); clearPreview(); setFailure(''); setNotice('请依据最新回执重新预览；不会重复提交已成功行。') } catch { setFailure('回执未能刷新，原预览保留。') } finally { setBusy(false) } }}>核对最新回执</Button>}
  </details>
}
