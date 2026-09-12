import { useMemo, useState } from 'react'
import { message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { useAuth } from '../../auth/AuthContext'
import { eventApi } from '../../services/events'
import { suggestionsApi, type WorkSuggestion } from '../../services/suggestions'
import {
  ACTION_LABELS,
  PRIORITY_META,
  WORKFLOW_FILTERS,
  buildSuggestionDetail,
  getSuggestionRoute,
  getSuggestionWorkflowBucket,
  numericTargetId,
  type SuggestionWorkflowFilter,
} from './suggestionPresentation'
import './Suggestions.css'

const Suggestions: React.FC = () => {
  const navigate = useNavigate()
  const { user, sessionEpoch } = useAuth()
  const canWrite = user?.role === 'admin' || user?.role === 'analyst'
  const queryClient = useQueryClient()
  const [workflowFilter, setWorkflowFilter] = useState<SuggestionWorkflowFilter>('all')
  const [offset, setOffset] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detailTab, setDetailTab] = useState<'facts' | 'inferences' | 'suggestions'>('facts')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['suggestions', user?.id, sessionEpoch, workflowFilter, offset],
    queryFn: () => suggestionsApi.list({ limit: 20, offset, status: 'open', workflow: workflowFilter }),
    refetchInterval: 60_000,
  })

  const convertEventMutation = useMutation({
    mutationFn: (eventId: number) => eventApi.convertToCase(eventId),
    onSuccess: async (result) => {
      message.success(result.message || '事件已转案件')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['suggestions'] }),
        queryClient.invalidateQueries({ queryKey: ['events'] }),
        queryClient.invalidateQueries({ queryKey: ['cases'] }),
      ])
      navigate(`/cases?caseId=${result.case_id}`)
    },
    onError: (error: Error) => message.error(`转案件失败：${error.message}`),
  })

  const suggestions = isError ? [] : data?.suggestions ?? []
  const visibleSuggestions = suggestions
  const stats = isError ? undefined : data?.summary
  const selectedSuggestion = visibleSuggestions.find(item => item.id === selectedId) ?? visibleSuggestions[0] ?? null
  const selectedDetail = useMemo(() => buildSuggestionDetail(selectedSuggestion), [selectedSuggestion])
  const highPriorityShare = stats ? (stats.total > 0 ? Math.round((stats.priority.high / stats.total) * 100) : 0) : null
  const detailTabItems = [
    { key: 'facts' as const, label: '事实', items: selectedDetail.facts },
    { key: 'inferences' as const, label: '推断', items: selectedDetail.inferences },
    { key: 'suggestions' as const, label: '建议', items: selectedDetail.suggestions },
  ]
  const activeDetail = detailTabItems.find(item => item.key === detailTab) ?? detailTabItems[0]

  const handleAction = (suggestion: WorkSuggestion) => {
    const targetId = numericTargetId(suggestion)
    switch (suggestion.action) {
      case 'convert_event_to_case':
        if (canWrite && targetId) convertEventMutation.mutate(targetId)
        break
      default:
        {
          const route = getSuggestionRoute(suggestion)
          if (route) {
            navigate(route)
          } else {
            message.info('该待办仅支持人工复核，不自动创建执行记录')
          }
        }
    }
  }

  const actionBusy = convertEventMutation.isPending

  return (
    <div className="page suggestions-page sg-redesign">
      <section className="sg-hero">
        <div className="sg-hero-title">
          <h1>待判断事项</h1>
          <p>处理必要资料补充和已有成果确认，不以经验卡或报告是否生成为每案必办条件。</p>
        </div>

        <div className="sg-notice">
          案件可以正常保存和使用。奖金核算的材料门槛只作用于核算，不阻塞案件主流程。
        </div>

        <div className="sg-title-actions">
          <button className="btn-ghost-sm" onClick={() => navigate('/workbench')}>返回日常工作</button>
          <button className="btn-ghost-sm" onClick={() => queryClient.invalidateQueries({ queryKey: ['suggestions'] })}>刷新</button>
        </div>
      </section>

      <section className="sg-workbench">
        <aside className="card sg-rail">
          <div className="card-head">
            <span className="ico">◆</span>
            <span className="ti">待办类型</span>
          </div>
          <div className="sg-rail-list">
            {WORKFLOW_FILTERS.map(filter => {
              const count = stats ? (filter.value === 'all' ? stats.total : stats.workflow[filter.value] ?? 0) : '待确认'
              return (
                <button
                  key={filter.value}
                  className={`sg-rail-item${workflowFilter === filter.value ? ' on' : ''}`}
                  onClick={() => {
                    setWorkflowFilter(filter.value)
                    setOffset(0)
                    setSelectedId(null)
                  }}
                >
                  <span>{filter.label}</span>
                  <b>{count}</b>
                </button>
              )
            })}
          </div>
          <div className="sg-rail-foot">
            <span>生成时间</span>
            <strong>{data ? dayjs(data.generated_at).format('HH:mm:ss') : '自动刷新'}</strong>
          </div>
          <div className="sg-filter-actions">
            <button className="btn-ghost-sm" type="button" onClick={() => { setWorkflowFilter('all'); setOffset(0); setSelectedId(null) }}>重置筛选</button>
          </div>
        </aside>

        <main className="card sg-queue">
          <div className="card-head">
            <span className="ico">◆</span>
            <span className="ti">待判断队列</span>
            <span className="spacer" />
            <span className="chip accent">{visibleSuggestions.length} 项</span>
          </div>
          <div className="sg-status-tabs">
            <div className="sg-status-stat on"><span>全队列</span><b>{stats?.total ?? '待确认'}</b></div>
            <div className="sg-status-stat danger"><span>高优先级</span><b>{stats?.priority.high ?? '待确认'}</b></div>
            <div className="sg-status-stat info"><span>中优先级</span><b>{stats?.priority.medium ?? '待确认'}</b></div>
            <div className="sg-status-stat warn"><span>低优先级</span><b>{stats?.priority.low ?? '待确认'}</b></div>
            <div className="sg-status-stat done"><span>当前筛选</span><b>{!isError && data ? data.total : '待确认'}</b></div>
          </div>
          <div className="sg-table-head">
            <span>优先级</span>
            <span>目标 / 案件编号</span>
            <span>待办类型</span>
            <span>事项依据 / 关键缺口</span>
            <span>事项分类</span>
            <span>下一步安全动作</span>
            <span>状态</span>
            <span>更新时间</span>
          </div>
          <div className="card-body">
            {isError ? (
              <div className="empty-state" role="alert" style={{ height: 300 }}>
                <div>待办读取失败，请刷新重试。</div>
                <span>当前不能确认待办数量和处理状态。</span>
              </div>
            ) : isLoading ? (
              <div className="empty-state" style={{ height: 300 }}>
                <div className="icon">⌛</div>
                <div>正在读取待判断事项</div>
              </div>
            ) : visibleSuggestions.length === 0 ? (
              <div className="empty-state" style={{ height: 300 }}>
                <div className="icon">✓</div>
                <div>当前没有待处理待办</div>
                <span>当前页未返回待判断事项，不代表案件办结或资料全部齐备。</span>
              </div>
            ) : (
              <div className="sg-list">
                {visibleSuggestions.map((suggestion) => {
                  const priority = PRIORITY_META[suggestion.priority] ?? PRIORITY_META.medium
                  const bucket = getSuggestionWorkflowBucket(suggestion)
                  return (
                    <button
                      key={suggestion.id}
                      className={`sg-row ${priority.cls}${selectedSuggestion?.id === suggestion.id ? ' on' : ''}`}
                      onClick={() => setSelectedId(suggestion.id)}
                    >
                      <span className="sg-priority">{priority.label}</span>
                      <span className="sg-target">{suggestion.target_type}:{String(suggestion.target_id)}</span>
                      <span className="sg-bucket">{WORKFLOW_FILTERS.find(filter => filter.value === bucket)?.label ?? bucket}</span>
                      <span className="sg-row-main">
                        <strong>{suggestion.title}</strong>
                        <small>{suggestion.description}</small>
                      </span>
                      <span className="sg-current-blocker">{getSuggestionWorkflowBucket(suggestion) === 'bonus_metric_gap' ? '核算指标' : getSuggestionWorkflowBucket(suggestion) === 'bonus_material_gap' ? '材料佐证' : WORKFLOW_FILTERS.find(filter => filter.value === bucket)?.label ?? bucket}</span>
                      <span className="sg-action">{ACTION_LABELS[suggestion.action] ?? '人工处理'}</span>
                      <span className="sg-status">{suggestion.status === 'open' ? '待处理' : suggestion.status}</span>
                      <span className="sg-time">{dayjs(suggestion.created_at).format('HH:mm')}</span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
          <div className="sg-filter-actions">
            <span>本页 {suggestions.length} 项 / 当前筛选 {!isError && data ? data.total : '待确认'} 项</span>
            <button className="btn-ghost-sm" disabled={offset === 0 || isLoading} onClick={() => { setOffset(Math.max(0, offset - 20)); setSelectedId(null) }}>上一页</button>
            <button className="btn-ghost-sm" disabled={isError || isLoading || !data?.has_more} onClick={() => { setOffset(offset + 20); setSelectedId(null) }}>下一页</button>
          </div>
        </main>

        <aside className="card sg-detail">
          <div className="sg-detail-header">
            <div>
              <strong>{selectedDetail.targetLabel}</strong>
              <span>{selectedDetail.targetLabel}</span>
            </div>
            <b>{selectedSuggestion ? (PRIORITY_META[selectedSuggestion.priority]?.label ?? selectedSuggestion.priority) : '未选择'}</b>
          </div>
          <div className="sg-detail-body">
            <div className="sg-blocker">
              <span>当前事项</span>
              <strong>{selectedDetail.blocker}</strong>
              <small>按实际需要补充资料或判断已有成果，不自动改变案件办结状态。</small>
            </div>
            <div className="sg-detail-tabbar">
              {detailTabItems.map(item => (
                <button
                  key={item.key}
                  className={detailTab === item.key ? 'on' : ''}
                  onClick={() => setDetailTab(item.key)}
                  type="button"
                >
                  {item.label}
                </button>
              ))}
            </div>
            <section className="sg-detail-section">
              <h3>{activeDetail.label}要素</h3>
              <ul>{activeDetail.items.map(item => <li key={item}>{item}</li>)}</ul>
            </section>
            <div className="sg-evidence-list">
              <h3>引用依据</h3>
              {selectedDetail.facts.slice(0, 3).map((item, index) => (
                <div key={`${item}-${index}`} className="sg-evidence-row">
                  <span>依据 {index + 1}</span>
                  <strong>{item}</strong>
                </div>
              ))}
            </div>
            <div className="sg-boundary">{selectedDetail.boundary}</div>
            <button
              className="btn-primary sg-detail-action"
              disabled={!selectedSuggestion || actionBusy || (!canWrite && selectedSuggestion.action === 'convert_event_to_case')}
              onClick={() => selectedSuggestion && handleAction(selectedSuggestion)}
            >
              {selectedSuggestion ? (ACTION_LABELS[selectedSuggestion.action] ?? '处理') : '选择待办'}
            </button>
          </div>
        </aside>
      </section>

      <section className="sg-bottom-status">
        <div className="sg-batch-progress">
          <h3>全队列优先级分布</h3>
          <span>高优先级 {stats?.priority.high ?? '待确认'} / {stats?.total ?? '待确认'}</span>
          <div className="sg-progress"><i style={{ width: `${highPriorityShare ?? 0}%` }} /></div>
          <b>{highPriorityShare === null ? '待确认' : `${highPriorityShare}%`}</b>
        </div>
        <div className="sg-skip-reasons">
          <h3>全队列资料缺口</h3>
          <span>材料缺失 {stats ? stats.workflow.bonus_material_gap ?? 0 : '待确认'}</span>
          <span>指标缺失 {stats ? stats.workflow.bonus_metric_gap ?? 0 : '待确认'}</span>
          <span>坐标缺失 {stats ? stats.workflow.coordinate_gap ?? 0 : '待确认'}</span>
        </div>
        <div className="sg-fallback-state">
          <h3>统计口径</h3>
          <span>分类与优先级统计来自服务端全授权未处理队列，列表按当前分类分页。</span>
          <span>不包含完成量、今日复核量及运行健康状态。</span>
        </div>
      </section>
    </div>
  )
}

export default Suggestions
