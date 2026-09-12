import { App as AntdApp } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { workbenchApi } from '../services/workbench'
import { STAGE_LABELS } from '../pages/Workbench/workbenchPresentation'


export default function ActiveWorkSessionBar() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { message } = AntdApp.useApp()
  const canTrack = user?.role === 'admin' || user?.role === 'analyst'
  const activeQuery = useQuery({
    queryKey: ['workbench-active-session'],
    queryFn: workbenchApi.activeSession,
    enabled: canTrack,
    refetchInterval: 60_000,
  })
  const active = activeQuery.data
  const eventMutation = useMutation({
    mutationFn: ({ event }: { event: 'completed' | 'abandoned' }) => (
      workbenchApi.recordEvent(active!.id, event)
    ),
    onSuccess: async (_, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['workbench-active-session'] }),
        queryClient.invalidateQueries({ queryKey: ['workbench-today'] }),
        queryClient.invalidateQueries({ queryKey: ['workbench-metrics'] }),
      ])
      message.success(variables.event === 'completed' ? '任务已完成并计入效率样本' : '任务已放弃')
    },
    onError: (error: Error) => message.error(`任务状态更新失败：${error.message}`),
  })

  if (!canTrack || !active) return null

  return (
    <div className="active-work-session" role="status">
      <span className="active-work-pulse" />
      <span className="active-work-label">进行中</span>
      <strong>{STAGE_LABELS[active.task_type]}</strong>
      <code>{active.source_type}:{active.source_id ?? '—'}</code>
      <span className="active-work-hint">跨页 {active.page_transitions} 次 · 仅记录流程指标</span>
      <span className="active-work-spacer" />
      <button onClick={() => navigate('/workbench')}>返回工作台</button>
      <button onClick={() => eventMutation.mutate({ event: 'abandoned' })} disabled={eventMutation.isPending}>放弃</button>
      <button className="active-work-complete" onClick={() => eventMutation.mutate({ event: 'completed' })} disabled={eventMutation.isPending}>完成任务</button>
    </div>
  )
}
