import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Input, Space, Table } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { mapLedgerImportsApi, type MapFieldDecisionRequest, type MapFieldGroup, type MapImportField } from '../../services/mapLedgerImports'
import { displayMapValue, groupLabels, mapImportError, valueStateLabels } from './mapLedgerPresentation'

export default function MapFieldDecision({ claimId, group, fields, onComplete, onClose }: {
  claimId: number; group: MapFieldGroup; fields: MapImportField[]; onComplete: (runId: string) => void; onClose: () => void
}) {
  const { user, sessionEpoch } = useAuth()
  const [note, setNote] = useState(''), [busy, setBusy] = useState(false), [failure, setFailure] = useState('')
  const [frozen, setFrozen] = useState<MapFieldDecisionRequest | null>(null)
  const mounted = useRef(true), busyRef = useRef(false)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const view = useQuery({ queryKey: ['map-field-decision', user?.id, sessionEpoch, claimId, group], gcTime: 0, retry: false,
    queryFn: ({ signal }) => mapLedgerImportsApi.fieldDecisionPreview(claimId, group, signal) })
  const data = view.isSuccess && !view.isFetching ? view.data : undefined
  const submit = async () => {
    if (busyRef.current || (!frozen && (!data?.can_resolve || !note.trim()))) return
    busyRef.current = true; setBusy(true); setFailure('')
    const payload = frozen || { group, request_id: crypto.randomUUID(), note: note.trim(),
      expected_asset_version: data!.asset_version, expected_decision_id: data!.decision_id }
    setFrozen(payload)
    try {
      const result = await mapLedgerImportsApi.fieldDecision(claimId, payload)
      if (mounted.current) onComplete(result.id)
    } catch (error) {
      if (!mounted.current) return
      const detail = mapImportError(error)
      if (detail.code === 'plan_stale') { setFrozen(null); void view.refetch() }
      setFailure(`${detail.message}。理由和本页输入保留；只有明确过期后才重新比较，结果不确定时继续使用原请求。`)
    } finally { busyRef.current = false; if (mounted.current) setBusy(false) }
  }
  const keys = data ? Array.from(new Set([...Object.keys(data.current), ...Object.keys(data.candidate)])) : []
  return <section aria-label="字段组来源冲突核对">
    <h4>核对并采用：{groupLabels[group]}</h4>
    <p>仅明确采用当前来源的完整字段组，不自动拼接值、单位或口径；原导入行保留，其他组不重新采用。</p>
    {view.isError && <Alert type="error" message="当前字段或来源决定读取失败，不能据旧缓存采纳。" />}
    <Button disabled={busy || !!frozen} loading={view.isFetching} onClick={() => void view.refetch()}>刷新当前值进行比较</Button>
    {data && <>
      <p>设施 #{data.asset_id} · 当前版本 {data.asset_version} · 来源 #{data.source_id} · {valueStateLabels[data.state] || data.state}</p>
      <Table size="small" rowKey="field" pagination={false} dataSource={keys.map(field => ({ field, current: data.current[field], candidate: data.candidate[field] }))} columns={[
        { title: '字段', dataIndex: 'field', render: key => fields.find(item => item.key === key)?.label || key },
        { title: '当前采用', dataIndex: 'current', render: displayMapValue }, { title: '该行资料', dataIndex: 'candidate', render: displayMapValue },
      ]} />
      {!data.can_resolve && <Alert type="warning" message="这份资料不在当前有效期，不能直接覆盖当前字段；保留历史声明。" />}
    </>}
    <label>明确采用理由<Input.TextArea aria-label="字段组采用理由" value={note} maxLength={1000} disabled={busy || !!frozen}
      onChange={event => setNote(event.target.value)} placeholder="请说明核对依据，不自动生成理由" /></label>
    {failure && <Alert type="warning" showIcon message={failure} />}
    {frozen && <p>提交结果待确认，理由、设施版本和请求标识已固定。请使用原请求核对重试。</p>}
    <Space><Button type="primary" disabled={busy || (!frozen && (!data?.can_resolve || !note.trim()))} onClick={() => void submit()}>
      {frozen ? '用原决定核对并重试' : '确认采用该完整字段组'}</Button>
      <Button disabled={busy || !!frozen} onClick={() => { if (!note || window.confirm('放弃当前尚未提交的采用理由？')) onClose() }}>返回回执</Button></Space>
  </section>
}
