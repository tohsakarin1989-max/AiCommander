import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Form, Input, Pagination, Select } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import type { FacilitySection } from '../../services/facilityAnalysis'
import { mapDataIssuesApi, type MapIssueGroup } from '../../services/mapDataIssues'

export const issueGroupLabels: Record<MapIssueGroup, string> = {
  identity: '名称或编号', coordinates: '位置或坐标依据', water_cut: '含水率及测量口径',
  production: '产量及生产属性', other: '其他来源问题',
}

export function LedgerOriginalButton({ runId, filename }: { runId: string; filename: string }) {
  const { user, sessionEpoch } = useAuth()
  const identity = `${user?.id}:${sessionEpoch}:${runId}`
  const current = useRef(identity)
  current.current = identity
  useEffect(() => () => { current.current = '' }, [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const download = async () => {
    const started = identity
    setBusy(true); setError(false)
    try {
      const blob = await mapDataIssuesApi.original(runId)
      if (current.current !== started) return
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = filename.replace(/[\\/\x00-\x1f]/g, '_') || '台账原件'
      anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch { if (current.current === started) setError(true) }
    finally { if (current.current === started) setBusy(false) }
  }
  return <><Button loading={busy} onClick={() => void download()}>下载台账原件</Button>
    {error && <p role="alert">原件未留存、已撤销、校验失败或当前不可访问；未提供旧缓存。</p>}</>
}

export default function FacilityDataIssues({ assetId, production }: { assetId: number; production: FacilitySection }) {
  const { user, sessionEpoch } = useAuth()
  return <DataIssueForm key={`${user?.id}:${sessionEpoch}:${assetId}`} assetId={assetId} production={production} userId={user?.id} sessionEpoch={sessionEpoch} />
}

export function DataIssueForm({ assetId, production, userId, sessionEpoch }: {
  assetId: number; production: FacilitySection; userId?: number; sessionEpoch: number
}) {
  const [opened, setOpened] = useState(false)
  const [page, setPage] = useState(1)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [form] = Form.useForm<{ reference: string; field_group: MapIssueGroup; notes: string }>()
  const options = (production.items ?? []).flatMap(row => {
    if (typeof row.id === 'string' && /^claim:\d+$/.test(row.id)) {
      return [{ value: row.id, label: `台账 ${row.source_revision ?? '未标版本'} · 第 ${row.row_number ?? '?'} 行` }]
    }
    if (typeof row.version_id === 'number') {
      return [{ value: `version:${row.version_id}`, label: `设施版本 ${row.version ?? row.version_id}` }]
    }
    return []
  })
  const listing = useQuery({
    queryKey: ['map-data-issues', userId, sessionEpoch, assetId, page],
    queryFn: ({ signal }) => mapDataIssuesApi.list(assetId, page, signal),
    retry: false, gcTime: 0, staleTime: 0, enabled: opened,
  })
  const submit = async (values: { reference: string; field_group: MapIssueGroup; notes: string }) => {
    if (!options.some(option => option.value === values.reference)) {
      setMessage({ kind: 'error', text: '所选来源已变化，请重新选择；说明仍保留。' }); return
    }
    const [kind, id] = values.reference.split(':')
    setBusy(true); setMessage(null)
    try {
      await mapDataIssuesApi.create(assetId, values.notes, {
        field_group: values.field_group,
        ...(kind === 'claim' ? { source_claim_id: Number(id) } : { asset_version_id: Number(id) }),
      })
      form.resetFields(['notes'])
      setMessage({ kind: 'success', text: '问题已标注；设施正式资料未改动。' })
      setPage(1)
      void listing.refetch()
    } catch { setMessage({ kind: 'error', text: '未能确认标注保存，请稍后重试或核对当前来源权限；输入仍保留。' }) }
    finally { setBusy(false) }
  }
  return <details className="facility-data-issues" onToggle={event => setOpened(event.currentTarget.open)}>
    <summary>标注资料问题</summary>
    <p>指出需要核对的来源即可，不要求您修正坐标或生产台账；标注不等于问题已核实。</p>
    {!options.length ? <p role="status">暂无可引用的台账行或设施版本，不能补造来源；请先由管理员登记资料。</p>
      : <Form form={form} layout="vertical" initialValues={{ field_group: 'other' }} onFinish={submit} disabled={busy}>
        <Form.Item name="reference" label="依据哪条资料" rules={[{ required: true, message: '请选择正在核对的来源' }]}>
          <Select options={options} placeholder="选择台账行或设施版本" />
        </Form.Item>
        <Form.Item name="field_group" label="需要核对的内容" rules={[{ required: true }]}>
          <Select options={Object.entries(issueGroupLabels).map(([value, label]) => ({ value, label }))} />
        </Form.Item>
        <Form.Item name="notes" label="问题说明" rules={[{ required: true, whitespace: true, message: '请简要说明需要核对之处' }, { max: 2000 }]}>
          <Input.TextArea rows={3} maxLength={2000} placeholder="例如：台账这一行的产量单位没有写明，需要核对。" />
        </Form.Item>
        <Button htmlType="submit" loading={busy}>保存问题标注</Button>
        <p>提交后保存到系统。未提交的说明只留在本页，关闭后不会留存。</p>
      </Form>}
    {message && <Alert type={message.kind} message={message.text} />}
    <h4>已有问题标注</h4>
    {listing.isError ? <Alert type="warning" message="问题标注暂不可读，不代表没有记录。" action={<Button onClick={() => void listing.refetch()}>重试</Button>} />
      : listing.isPending ? <p role="status">正在读取…</p>
      : <>{!listing.data.items.length ? <p>当前可访问来源中暂无问题标注。</p>
        : <ul>{listing.data.items.map(row => <li key={row.id}>
          <strong>{issueGroupLabels[row.source_reference.field_group]}</strong>：{row.notes}
          <small> · 待核对，未修改正式资料</small>
        </li>)}</ul>}
        {listing.data.total > 10 && <Pagination current={page} pageSize={10} total={listing.data.total} onChange={setPage} showSizeChanger={false} />}</>}
  </details>
}
