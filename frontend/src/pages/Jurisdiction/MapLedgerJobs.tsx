import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Space } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { mapLedgerImportsApi, type MapFieldContract, type MapLedgerPreview, type MapLedgerRun } from '../../services/mapLedgerImports'
import { mapImportError } from './mapLedgerPresentation'
import MapImportPlan from './MapImportPlan'

export const ledgerJobLabels: Record<string, string> = {
  queued: '已接收，等待后台', parsing: '读取源行', planning: '核对变化', adopting: '整体采用中',
  ready_to_adopt: '有异常待核对', paused: '已暂停领取', cancelled: '已取消，暂存未采用',
  failed: '未完成，正式资料未部分更新', completed: '已整体采用', completed_with_errors: '合格记录已采用，异常保留',
}

export default function MapLedgerJobs({ sourceId, contract, onChanged }: {
  sourceId: number; contract: MapFieldContract; onChanged: () => void
}) {
  const { user, sessionEpoch } = useAuth(), cache = useQueryClient()
  const [selection, setSelection] = useState<{ run: MapLedgerRun; preview: MapLedgerPreview } | null>(null)
  const [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const alive = useRef(true), previous = useRef<string | null>(null)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const query = useQuery({ queryKey: ['map-ingest-runs', user?.id, sessionEpoch, sourceId, 0], gcTime: 0,
    queryFn: ({ signal }) => mapLedgerImportsApi.runs(sourceId, 0, signal),
    refetchInterval: state => state.state.data?.items.some(row => ['queued', 'parsing', 'planning', 'adopting'].includes(row.status)) ? 3000 : false })
  const rows = query.isSuccess ? query.data.items.filter(row => row.table_metadata?.job) : []
  useEffect(() => {
    const stamp = rows.filter(row => row.status.startsWith('completed')).map(row => row.id).join(',')
    if (previous.current !== null && previous.current !== stamp) onChanged()
    previous.current = stamp
  }, [query.data, onChanged])
  const action = async (run: MapLedgerRun, kind: 'pause' | 'resume' | 'cancel' | 'adopt' | 'preview') => {
    setBusy(true); setError('')
    try {
      if (kind === 'preview') {
        const preview = await mapLedgerImportsApi.jobPreview(run.id)
        if (alive.current) setSelection({ run, preview })
      } else {
        await mapLedgerImportsApi.control(run.id, kind, selection?.run.id === run.id ? selection.preview.plan_token : undefined)
        if (alive.current) setSelection(null)
        void cache.invalidateQueries({ queryKey: ['map-ingest-runs'] })
      }
    } catch (failure) { if (alive.current) setError(mapImportError(failure).message) }
    finally { if (alive.current) setBusy(false) }
  }
  if (query.isError) return <Alert type="warning" message="后台批次暂不可读，不表示没有任务；请刷新核对。" />
  if (!rows.length) return null
  const fullBlocked = selection?.run.table_metadata?.job && selection.preview.ledger_declaration?.mode === 'full'
    && ['failed', 'conflict', 'identity_pending'].some(key => selection.preview.counts[key as keyof typeof selection.preview.counts] > 0)
  return <section aria-label="可离页的后台台账批次"><h4>后台整理与续做</h4>
    <p>服务器已保存原件和进度，可以离页。正常资料按已确认来源规则整体采用；完整台账有异常时继续保留上一有效资料。</p>
    {rows.map(row => <div key={row.id}><strong>{row.filename}</strong> · {ledgerJobLabels[row.status] || row.status}
      <p>已读 {row.table_metadata?.job?.parsed_rows} 行 · 已核对 {row.table_metadata?.job?.planned_rows} 行 · {row.table_metadata?.job?.visibility === 'adopted' ? '已生效' : '尚未生效'}</p>
      {row.errors?.length > 0 && <p>{row.errors[0].message}</p>}
      <Space wrap>
        {['queued', 'parsing', 'planning'].includes(row.status) && <Button disabled={busy} onClick={() => void action(row, 'pause')}>暂停领取</Button>}
        {['paused', 'failed'].includes(row.status) && <Button disabled={busy} onClick={() => void action(row, 'resume')}>{row.status === 'failed' ? '按当前权限重新核对并续做' : '继续整理'}</Button>}
        {row.status === 'ready_to_adopt' && <Button disabled={busy} onClick={() => void action(row, 'preview')}>查看异常与采用范围</Button>}
        {['queued', 'parsing', 'planning', 'paused', 'ready_to_adopt', 'failed'].includes(row.status) && <Button disabled={busy} onClick={() => {
          if (window.confirm('取消这个未采用批次？原件与已读行会保留，不删除正式设施。')) void action(row, 'cancel')
        }}>取消剩余处理</Button>}
      </Space>
    </div>)}
    {error && <Alert type="warning" message={error} />}
    {selection && <><MapImportPlan preview={selection.preview} fields={contract.fields} />
      {fullBlocked && <Alert type="warning" message="完整台账有异常，不能只采用半批；请修正原表或模板后重新准备。原件和异常回执保留。" />}
      <Button disabled={busy || !!fullBlocked || !selection.preview.publishable} onClick={() => void action(selection.run, 'adopt')}>按已核对预览采用合格记录</Button>
      <Button disabled={busy} onClick={() => setSelection(null)}>收起预览</Button></>}
  </section>
}
