import { useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import CaseSearch from '../../components/CaseSearch'
import { mapFoundationApi } from '../../services/mapFoundation'
import { intelligentQueriesApi, type QueryTask } from '../../services/intelligentQueries'

export default function QueryClarification({ task, enabled, onUpdated }: { task: QueryTask; enabled: boolean; onUpdated: () => void }) {
  const { user, sessionEpoch } = useAuth()
  const clarification = task.clarification
  const [choice, setChoice] = useState<number | null>(null)
  const frozen = useRef<{ clarification_id: string; request_id: string; value: number } | null>(null)
  const areas = useQuery({ queryKey: ['clarification-areas', user?.id, sessionEpoch, task.id],
    queryFn: mapFoundationApi.listAreas, enabled: enabled && clarification?.field === 'area_id', retry: false, gcTime: 0 })
  const submit = useMutation({ mutationFn: (payload: NonNullable<typeof frozen.current>) => intelligentQueriesApi.clarify(task.id, payload),
    onSuccess: onUpdated })
  if (!clarification || task.status !== 'waiting_clarification') return null
  const expiry = Date.parse(clarification.expires_at)
  const expired = !Number.isFinite(expiry) || expiry <= Date.now()
  const disabled = !enabled || submit.isPending || expired
  const send = (value: number) => {
    if (disabled) return
    // An uncertain network outcome is retried with exactly the same key/value.
    if (!frozen.current) frozen.current = { clarification_id: clarification.id, request_id: crypto.randomUUID(), value }
    submit.mutate(frozen.current)
  }
  return <section className="query-clarification" aria-label="补充一个关键条件">
    <h2>{clarification.prompt}</h2>
    <p>等待期间不占用分析任务；到期时间：{clarification.expires_at}。继续时将重新核验权限与数据版本。</p>
    {expired ? <p role="status">本次等待已到期，请刷新状态后重新提问。</p> : <>
      {clarification.field === 'case_id' && <CaseSearch disabled={disabled || Boolean(frozen.current)}
        areaId={task.source_context?.area_id} onChoose={item => send(item.id)} />}
      {clarification.field === 'area_id' && (areas.isError ? <p role="alert">区域列表读取失败，未使用旧缓存。<button onClick={() => void areas.refetch()}>重试</button></p>
        : <label>要查看的授权区域<select disabled={disabled || Boolean(frozen.current)} value={choice ?? ''} onChange={event => setChoice(Number(event.target.value) || null)}>
          <option value="">请选择区域</option>{(areas.data || []).filter(area => area.status === 'active').map(area => <option value={area.id} key={area.id}>{area.name}</option>)}
        </select><button type="button" disabled={disabled || !choice} onClick={() => choice && send(choice)}>继续原问题</button></label>)}
      {submit.error && <p role="alert">补充未得到确认，可能是网络或权限发生变化。
        <button disabled={disabled || !frozen.current} onClick={() => frozen.current && submit.mutate(frozen.current)}>使用同一请求重试</button>
        <button onClick={onUpdated}>刷新任务状态</button></p>}
    </>}
  </section>
}
