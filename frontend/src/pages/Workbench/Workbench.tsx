import { useMemo, useState } from 'react'
import { App as AntdApp } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { workbenchApi, type WorkbenchTask } from '../../services/workbench'
import {
  STAGE_LABELS,
  buildPipelineProgress,
  formatDuration,
  getTaskActionLabel,
  sortWorkbenchTasks,
} from './workbenchPresentation'
import './Workbench.css'


const Workbench: React.FC = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { message } = AntdApp.useApp()
  const { user } = useAuth()
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const todayQuery = useQuery({
    queryKey: ['workbench-today'],
    queryFn: workbenchApi.today,
    refetchInterval: 60_000,
  })
  const metricsQuery = useQuery({
    queryKey: ['workbench-metrics', user?.role],
    queryFn: () => workbenchApi.metrics(30),
    enabled: user?.role === 'admin' || user?.role === 'analyst',
  })
  const startMutation = useMutation({
    mutationFn: workbenchApi.startSession,
    onSuccess: async ({ created }, task) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['workbench-active-session'] }),
        queryClient.invalidateQueries({ queryKey: ['workbench-today'] }),
      ])
      message.success(created ? '任务计时已开始' : '已继续当前任务')
      navigate(task.target_path)
    },
    onError: (error: Error) => message.error(`无法开始任务：${error.message}`),
  })

  const data = todayQuery.data
  const tasks = useMemo(() => sortWorkbenchTasks(data?.tasks ?? []), [data?.tasks])
  const selected = tasks.find(item => item.id === selectedId) ?? tasks[0] ?? null
  const progress = buildPipelineProgress({
    total_cases: data?.summary.total_cases ?? 0,
    completed: data?.summary.completed ?? 0,
  })
  const metrics = metricsQuery.data

  const openTask = (task: WorkbenchTask) => {
    if (user?.role === 'viewer') {
      navigate(task.target_path)
      return
    }
    startMutation.mutate(task)
  }

  if (todayQuery.isLoading) {
    return <div className="empty-state" style={{ height: '70vh' }}><span className="icon">⌛</span>正在整理今日研判任务</div>
  }

  if (todayQuery.isError || !data) {
    return (
      <div className="empty-state" style={{ height: '70vh' }}>
        <span className="icon">!</span>
        <span>今日工作台暂不可用，案件主流程不受影响</span>
        <button className="btn-ghost" onClick={() => todayQuery.refetch()}>重新读取</button>
      </div>
    )
  }

  return (
    <div className="page-scrollable workbench-page">
      <section className="wb-hero">
        <div className="wb-hero-main">
          <span className="wb-kicker">v2.8 · DAILY ANALYSIS DESK</span>
          <h1>今日研判工作台</h1>
          <p>每起案件只给一个明确下一步，把数据核验、经验沉淀和报告复核串成可完成、可度量的日常流程。</p>
        </div>
        <div className="wb-progress-block" aria-label="当前闭环完成度">
          <div className="wb-progress-copy"><span>当前闭环完成度</span><strong>{progress.percent}%</strong></div>
          <div className="wb-progress-track"><i style={{ width: `${progress.percent}%` }} /></div>
          <small>{progress.label}</small>
        </div>
        <button className="btn-ghost" onClick={() => void todayQuery.refetch()}>刷新任务</button>
      </section>

      <section className="wb-kpis" aria-label="今日工作量">
        <div className="wb-kpi wb-kpi--urgent"><span>需处理</span><strong>{data.summary.actionable_cases}</strong><small>起案件</small></div>
        <div className="wb-kpi"><span>数据核验</span><strong>{data.summary.data_review}</strong><small>先补研判底座</small></div>
        <div className="wb-kpi"><span>经验沉淀</span><strong>{data.summary.experience_review}</strong><small>生成或复核</small></div>
        <div className="wb-kpi"><span>报告复核</span><strong>{data.summary.report_review}</strong><small>生成或确认</small></div>
        <div className="wb-kpi wb-kpi--done"><span>当前闭环</span><strong>{data.summary.completed}</strong><small>事实已人工确认</small></div>
        <div className="wb-kpi"><span>Agent 审批</span><strong>{data.summary.pending_approvals}</strong><small>不阻塞主流程</small></div>
      </section>

      <section className="wb-pipeline" aria-label="案件研判流程">
        {data.pipeline.map((item, index) => (
          <div key={item.stage} className={`wb-pipeline-node${item.stage === 'completed' ? ' done' : ''}`}>
            <span>{String(index + 1).padStart(2, '0')}</span>
            <strong>{item.label}</strong>
            <b>{item.count}</b>
          </div>
        ))}
      </section>

      <section className="wb-main-grid">
        <section className="wb-queue card">
          <div className="card-head">
            <span className="ico">◆</span><span className="ti">优先任务队列</span>
            <span className="spacer" /><span className="chip accent">{tasks.length} 项</span>
          </div>
          <div className="wb-list-head"><span>优先级</span><span>案件</span><span>当前节点</span><span>任务</span><span>影响</span></div>
          <div className="wb-task-list">
            {tasks.length === 0 ? (
              <div className="empty-state"><span className="icon">✓</span><span>当前案件均已完成本轮闭环</span></div>
            ) : tasks.map(task => (
              <button
                key={task.id}
                className={`wb-task-row wb-task-row--${task.priority}${selected?.id === task.id ? ' on' : ''}`}
                onClick={() => setSelectedId(task.id)}
              >
                <span className="wb-priority">{task.priority === 'high' ? '优先' : '常规'}</span>
                <span className="wb-case-no">{task.case_number}</span>
                <span className="wb-stage">{STAGE_LABELS[task.stage]}</span>
                <span className="wb-task-title"><strong>{task.title}</strong><small>{task.why}</small></span>
                <span className="wb-impact">{task.impact}</span>
              </button>
            ))}
          </div>
        </section>

        <aside className="wb-detail card">
          <div className="card-head"><span className="ico">▤</span><span className="ti">下一步行动卡</span></div>
          {selected ? (
            <div className="wb-detail-body">
              <div className="wb-detail-label">{selected.case_number} · {STAGE_LABELS[selected.stage]}</div>
              <h2>{selected.title}</h2>
              <dl>
                <div><dt>事实状态</dt><dd>{selected.why}</dd></div>
                <div><dt>业务影响</dt><dd>{selected.impact}</dd></div>
                <div><dt>下一步</dt><dd>{selected.next_action}</dd></div>
              </dl>
              <div className="wb-evidence">
                <span>依据引用</span>
                {selected.evidence_refs.map(ref => <code key={ref}>{ref}</code>)}
              </div>
              <button
                className="btn-primary wb-start"
                disabled={startMutation.isPending}
                onClick={() => openTask(selected)}
              >
                {startMutation.isPending ? '正在建立任务…' : getTaskActionLabel(user!.role, selected)}
              </button>
              <small className="wb-detail-boundary">进入任务不会自动修改案件、经验卡或报告；完成状态由操作人主动确认。</small>
            </div>
          ) : <div className="empty-state"><span className="icon">✓</span>暂无待处理任务</div>}
        </aside>
      </section>

      <section className="wb-metrics card">
        <div className="card-head">
          <span className="ico">⌁</span><span className="ti">30 日实用性度量</span>
          <span className="spacer" />
          <span className={`chip${metrics?.business_acceptance_status === 'measurable' ? ' live' : ' warn'}`}>
            {metrics?.business_acceptance_status === 'measurable' ? '样本可评估' : `需累计 ${metrics?.sample_threshold ?? 20} 次`}
          </span>
        </div>
        {user?.role === 'viewer' ? (
          <div className="wb-metrics-boundary">只读账号可查看任务依据，不采集个人处理会话。</div>
        ) : metricsQuery.isLoading ? (
          <div className="wb-metrics-boundary">正在读取非敏感效率指标…</div>
        ) : metricsQuery.isError ? (
          <div className="wb-metrics-boundary">效率指标暂不可用，不影响任务处理。</div>
        ) : (
          <div className="wb-metrics-body">
            <div><span>统计范围</span><strong>{metrics?.scope === 'team' ? '全组' : '本人'}</strong></div>
            <div><span>已开始</span><strong>{metrics?.totals.started ?? 0}</strong></div>
            <div><span>已完成</span><strong>{metrics?.totals.completed ?? 0}</strong></div>
            <div><span>完成率</span><strong>{Math.round((metrics?.totals.completion_rate ?? 0) * 100)}%</strong></div>
            <div><span>平均耗时</span><strong>{formatDuration(metrics?.totals.avg_duration_seconds ?? null)}</strong></div>
            <div><span>平均跨页</span><strong>{metrics?.totals.avg_page_transitions ?? '待积累'}</strong></div>
            <p>{metrics?.measurement_boundary ?? '效率度量不采集敏感业务正文。'}</p>
          </div>
        )}
      </section>

      <div className="wb-boundary"><strong>人工复核边界</strong><span>{data.boundary}</span></div>
    </div>
  )
}

export default Workbench
