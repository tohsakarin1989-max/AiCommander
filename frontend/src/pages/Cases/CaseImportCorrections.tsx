import { useEffect, useState } from 'react'
import { Alert, Button, Input, Select, Spin } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { caseImportsApi, type FailedImportRow, type ImportCorrectionResult } from '../../services/caseImports'
import { changedImportFields, correctionReceiptState, importFieldLabels, importTimeZoneLabel } from './importCorrection'

interface Props {
  batchId: string
  onCorrected: (result: ImportCorrectionResult) => void
  onBusyChange: (busy: boolean) => void
}

export default function CaseImportCorrections(props: Props) {
  const { user, sessionEpoch } = useAuth()
  return <ScopedCaseImportCorrections key={`${props.batchId}:${user?.id}:${sessionEpoch}`} {...props} />
}

function ScopedCaseImportCorrections({ batchId, onCorrected, onBusyChange }: Props) {
  const { user, sessionEpoch } = useAuth()
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<FailedImportRow | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [failure, setFailure] = useState('')
  const [notice, setNotice] = useState('')
  const [mustRefresh, setMustRefresh] = useState(false)
  const [newerRow, setNewerRow] = useState<FailedImportRow | null>(null)
  const key = ['case-import-rows', user?.id, sessionEpoch, batchId]
  const rows = useQuery({ queryKey: key, enabled: open, retry: false,
    queryFn: ({ signal }) => caseImportsApi.getRows(batchId, signal) })
  useEffect(() => {
    if (!rows.isSuccess || !rows.data.retry_available) return
    onCorrected({ batch_id: rows.data.batch_id, created: 0,
      batch_created_total: rows.data.created_total, rows: rows.data.rows,
      errors: rows.data.rows.map(row => ({ row: row.row, error: row.error || '该行待核验' })) })
  }, [rows.data, rows.isSuccess, onCorrected])
  const mutation = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error('请选择失败行')
      return caseImportsApi.correct(batchId, selected.row, selected.revision, changedImportFields(selected.values, draft))
    },
    onSuccess: result => {
      onCorrected(result)
      if (result.created) { setSelected(null); setDraft({}) }
      else if (selected) {
        const updated = result.rows.find(row => row.row === selected.row)
        if (updated) setSelected(updated)
      }
      setMustRefresh(false); setNewerRow(null)
      setNotice(result.created ? `已修正并新增 ${result.created} 条案件` : '未新增案件，请查看最新失败原因')
      setFailure('')
      void client.invalidateQueries({ queryKey: key })
      void client.invalidateQueries({ queryKey: ['cases'] })
    },
    onError: () => {
      // Never silently rebase an old correction onto somebody else's revision.
      setMustRefresh(true)
      setFailure('提交未确认或记录已变化。修正输入仍保留，请刷新回执后核对；不要重新上传整批文件。')
    },
  })
  useEffect(() => {
    onBusyChange(mutation.isPending)
    return () => onBusyChange(false)
  }, [mutation.isPending, onBusyChange])

  const data = rows.isSuccess ? rows.data : undefined
  return <details className="cases-import-corrections" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>直接修正失败行</summary>
    {open && <div style={{ paddingTop: 12 }}>
      <p>只显示失败行；成功案件不会再次写入，原始文件值保留供追溯。</p>
      {rows.isPending && <Spin tip="读取失败行" />}
      {(rows.isError || failure) && <Alert type="error" showIcon message={failure || '回执读取失败或无权访问'} />}
      {notice && <Alert type="info" message={notice} />}
      <Button disabled={mutation.isPending || rows.isFetching} onClick={async () => {
        const refreshed = await rows.refetch()
        if (!refreshed.isSuccess) { setMustRefresh(true); setFailure('回执刷新失败，修正输入仍保留。'); return }
        if (!selected) { setMustRefresh(false); setFailure(''); return }
        const receipt = correctionReceiptState(selected, refreshed.data.rows)
        setNewerRow(receipt.state === 'changed' ? receipt.latest! : null)
        setMustRefresh(receipt.state !== 'same')
        setFailure(receipt.state === 'changed' ? '该行已被修改。请对照最新回执，再明确确认如何继续；本地修正未覆盖最新记录。'
          : receipt.state === 'absent' ? '该行已不在失败列表，可能已处理。输入暂存于本页供核对，不再重复提交此行。' : '')
      }}>刷新失败行</Button>
      {data && !data.retry_available && <p>历史批次未保存源行，无法在此修正，请由管理员核验原文件。</p>}
      {data?.retry_available && data.rows.length === 0 && <p>本批失败行已全部处理。</p>}
      {!!data?.rows.length && <>
        <Select aria-label="选择失败行" style={{ width: '100%', marginTop: 12 }}
          placeholder="选择需要修正的失败行" value={selected?.row} disabled={mutation.isPending}
          options={data.rows.map(row => ({ value: row.row, label: `第 ${row.row} 行：${row.error}` }))}
          onChange={number => {
            if (selected && Object.keys(changedImportFields(selected.values, draft)).length && !window.confirm('切换失败行会放弃当前未提交修正，仍要切换吗？')) return
            const row = data.rows.find(item => item.row === number)!
            setSelected(row); setDraft(Object.fromEntries(Object.entries(row.values).map(([field, value]) => [field, value ?? ''])))
            setFailure(''); setNotice(''); setMustRefresh(false); setNewerRow(null)
          }} />
      </>}
        {selected && <div>
          <p>第 {selected.row} 行 · 修正版本 {selected.revision} · 无时区时间按 {importTimeZoneLabel(selected.time_zone)} 解释</p>
          {newerRow && <section aria-label="最新失败行回执"><p>最新修正版本 {newerRow.revision}：{newerRow.error}</p>
            <dl>{Object.entries(newerRow.values).map(([field, value]) => <div key={field}><dt>{importFieldLabels[field] || field}</dt><dd>{value ?? '未填写'}</dd></div>)}</dl>
            <Button onClick={() => { setSelected(newerRow); setNewerRow(null); setMustRefresh(false); setFailure(''); setNotice('已采用最新回执作为比较基准，请核对下方仍保留的修正输入后提交。') }}>已核对最新回执，保留我的修正继续</Button>
          </section>}
          {Object.keys(selected.values).map(field => <label key={field} style={{ display: 'block', margin: '8px 0' }}>
            {importFieldLabels[field] || field}
            <Input.TextArea aria-label={`修正${importFieldLabels[field] || field}`} autoSize={{ minRows: 1, maxRows: 5 }}
              disabled={mutation.isPending} value={draft[field] ?? ''} maxLength={10000}
              onChange={event => setDraft(previous => ({ ...previous, [field]: event.target.value }))} />
          </label>)}
          <Button type="primary" loading={mutation.isPending}
            disabled={mustRefresh || !Object.keys(changedImportFields(selected.values, draft)).length || mutation.isPending}
            onClick={() => mutation.mutate()}>仅重试此失败行</Button>
        </div>}
    </div>}
  </details>
}
