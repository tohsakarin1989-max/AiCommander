import { useEffect, useRef } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { intelligentQueriesApi, type QueryCard } from '../../services/intelligentQueries'
import { ProfileAggregateContent } from './ProfileAggregateContent'
import { queryIdValid, textValue } from './queryPresentation'

const active = (status?: string) => ['pending', 'retry', 'processing'].includes(status || '')
export function continuationPollInterval(status: string | undefined, elapsedMs: number, error: unknown) {
  return !error && active(status) && elapsedMs < 180_000 ? 3000 : false
}
const statuses: Record<string, string> = { pending: '等待后台处理', retry: '等待继续处理', processing: '正在分批统计',
  completed: '后台处理结束', cancelled: '后台统计已取消', superseded: '源资料已变化，原统计失效', failed: '后台统计未完成' }
const phases: Record<string, string> = { cases: '遍历案件', references: '核对成果依据', events: '整理事件背景', publish: '核验并保存结果' }

function failure(error: unknown) {
  const status = (error as { response?: { status?: number }; status?: number })?.response?.status
    ?? (error as { status?: number })?.status
  return [401, 403, 404].includes(status || 0)
    ? '账号、授权范围或来源已变化，不能继续显示旧统计。'
    : '暂时无法核验后台统计，旧内容已隐藏；这不代表没有匹配资料。'
}

function RunningContinuation({ id, partial }: { id: string; partial: Record<string, unknown> }) {
  const { user, sessionEpoch } = useAuth()
  const mounted = useRef(true)
  const startedAt = useRef(Date.now())
  const identity = `${user?.id}:${sessionEpoch}:${id}`
  const currentIdentity = useRef(identity)
  currentIdentity.current = identity
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const enabled = Boolean(user && ['admin', 'analyst'].includes(user.role) && queryIdValid(id))
  const task = useQuery({
    queryKey: ['query-aggregate-continuation', user?.id, sessionEpoch, id],
    queryFn: ({ signal }) => intelligentQueriesApi.readContinuation(id, signal),
    enabled, retry: false, staleTime: 0, gcTime: 0, refetchOnMount: 'always',
    refetchInterval: query => continuationPollInterval(query.state.data?.status, Date.now() - startedAt.current, query.state.error),
    refetchIntervalInBackground: false,
  })
  const cancel = useMutation({
    mutationFn: ({ jobId }: { jobId: string; identity: string }) => intelligentQueriesApi.cancelContinuation(jobId),
    onSuccess: async (_response, variables) => {
      // A response from an unmounted query/session must not refresh another job.
      if (mounted.current && variables.identity === currentIdentity.current) await task.refetch()
    },
  })
  const error = task.error || cancel.error
  // Neither a previous job nor an unverified cache is a readable current result.
  const current = enabled && !error && task.isFetchedAfterMount && task.data?.id === id ? task.data : undefined
  if (!enabled) return <p role="alert">当前账号不能读取后台统计，或任务编号无效。</p>
  return <div className="query-continuation" aria-label="后台统计续跑">
    <h3>后台统计</h3>
    <p>沿用本次查询已经创建的任务；刷新仅查看进度，不会重复启动。</p>
    <div className="query-actions">
      <button type="button" disabled={task.isFetching || cancel.isPending} onClick={() => { cancel.reset(); void task.refetch() }}>刷新后台进度</button>
      {current && active(current.status) && <button type="button" disabled={cancel.isPending || task.isFetching}
        onClick={() => cancel.mutate({ jobId: id, identity })}>{cancel.isPending ? '正在取消…' : '取消后台统计'}</button>}
    </div>
    {error ? <p role="alert">{failure(error)}</p> : !current ? <p role="status">正在核验当前任务与读取权限…</p> : <>
      <p role="status">{statuses[current.status] || '后台状态未知'}。</p>
      <p>阶段：{phases[current.progress.phase] || '等待确认'}；已遍历 {textValue(current.progress.scanned_cases)} / {current.progress.total_cases == null ? '待确定' : textValue(current.progress.total_cases)} 起案件。</p>
      <p>数据截点：{textValue(current.as_of)}。</p>
      {active(current.status) && <>
        <p>自动更新最多 3 分钟，之后可手动刷新；关闭页面不会中断后台续跑。</p>
        <details><summary>查看交互查询的部分统计（不是后台最终结果）</summary><ProfileAggregateContent data={partial} /></details>
      </>}
      {current.status === 'completed' && (current.result
        ? <section aria-label="后台完成统计"><h3>后台完成统计</h3><ProfileAggregateContent data={current.result} /></section>
        : <p role="alert">任务已结束但没有可读取结果，不能据此认定统计为零。</p>)}
      {current.status === 'superseded' && <p>旧结果不再展示；请根据更新后的资料重新查询，系统未自动重启旧任务。</p>}
      {current.status === 'cancelled' && <p>没有生成本次完整统计，不能将已遍历数量当作全量结果。</p>}
      {current.status === 'failed' && <p>分批统计未成功完成，不能据此判断没有符合条件的案件。请联系管理员检查后台处理状态。</p>}
    </>}
  </div>
}

export function ContinuationResult({ continuation, partial }: { continuation: NonNullable<QueryCard['continuation']>; partial: Record<string, unknown> }) {
  if (continuation.status === 'unavailable') return <>
    <p role="status">后台容量暂满，本次未创建续跑任务；以下仅为交互查询已完成的部分统计。</p>
    <ProfileAggregateContent data={partial} />
  </>
  return <RunningContinuation key={continuation.id} id={continuation.id} partial={partial} />
}
