import { useMemo, useState } from 'react'
import { message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { caseApi } from '../../services/cases'
import { eventApi } from '../../services/events'
import { suggestionsApi, type WorkSuggestion } from '../../services/suggestions'
import {
  ACTION_LABELS,
  PRIORITY_META,
  WORKFLOW_FILTERS,
  buildSuggestionDetail,
  buildSuggestionStats,
  filterSuggestionsByWorkflow,
  getSuggestionRoute,
  getSuggestionWorkflowBucket,
  numericTargetId,
  type SuggestionWorkflowFilter,
} from './suggestionPresentation'
import './Suggestions.css'

const Suggestions: React.FC = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [workflowFilter, setWorkflowFilter] = useState<SuggestionWorkflowFilter>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detailTab, setDetailTab] = useState<'facts' | 'inferences' | 'suggestions'>('facts')

  const { data, isLoading } = useQuery({
    queryKey: ['suggestions'],
    queryFn: () => suggestionsApi.list({ limit: 80, status: 'open' }),
    refetchInterval: 60_000,
  })

  const preprocessMutation = useMutation({
    mutationFn: (caseId: number) => caseApi.preprocessCase(caseId),
    onSuccess: async (result) => {
      message.success(result.message || '预处理任务已提交')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['suggestions'] }),
        queryClient.invalidateQueries({ queryKey: ['cases'] }),
      ])
    },
    onError: (error: Error) => message.error(`预处理失败：${error.message}`),
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

  const suggestions = data?.suggestions ?? []
  const visibleSuggestions = useMemo(() => filterSuggestionsByWorkflow(suggestions, workflowFilter), [suggestions, workflowFilter])
  const stats = useMemo(() => buildSuggestionStats(suggestions), [suggestions])
  const selectedSuggestion = visibleSuggestions.find(item => item.id === selectedId) ?? visibleSuggestions[0] ?? null
  const selectedDetail = useMemo(() => buildSuggestionDetail(selectedSuggestion), [selectedSuggestion])
  const completedCount = Math.max(0, (data?.total ?? suggestions.length) - suggestions.length)
  const reviewedToday = Math.min(suggestions.length, stats.priority.medium + stats.priority.low)
  const batchProgress = suggestions.length > 0 ? Math.round((reviewedToday / Math.max(suggestions.length, 1)) * 100) : 0
  const detailTabItems = [
    { key: 'facts' as const, label: '事实', items: selectedDetail.facts },
    { key: 'inferences' as const, label: '推断', items: selectedDetail.inferences },
    { key: 'suggestions' as const, label: '建议', items: selectedDetail.suggestions },
  ]
  const activeDetail = detailTabItems.find(item => item.key === detailTab) ?? detailTabItems[0]

  const handleAction = (suggestion: WorkSuggestion) => {
    const targetId = numericTargetId(suggestion)
    switch (suggestion.action) {
      case 'preprocess_case':
        if (targetId) preprocessMutation.mutate(targetId)
        break
      case 'convert_event_to_case':
        if (targetId) convertEventMutation.mutate(targetId)
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

  const actionBusy = preprocessMutation.isPending || convertEventMutation.isPending

  return (
    <div className="page suggestions-page sg-redesign">
      <section className="sg-hero">
        <div className="sg-hero-title">
          <h1>闭环研判工厂 <span>/</span> 研判待办中心</h1>
          <p>统一编排事实要素、推断结论、材料佐证和奖金核算，确保闭环合规、可追溯、可复用</p>
        </div>

        <div className="sg-notice">
          案件录入阶段可先提示、不强制保存；关键核算指标缺失时整案暂不测算。
        </div>

        <div className="sg-title-actions">
          <button className="btn-ghost-sm" onClick={() => queryClient.invalidateQueries({ queryKey: ['suggestions'] })}>刷新</button>
          <button className="btn-ghost-sm">按最新</button>
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
              const count = filter.value === 'all'
                ? suggestions.length
                : filterSuggestionsByWorkflow(suggestions, filter.value).length
              return (
                <button
                  key={filter.value}
                  className={`sg-rail-item${workflowFilter === filter.value ? ' on' : ''}`}
                  onClick={() => {
                    setWorkflowFilter(filter.value)
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
          <div className="sg-quick-filter">
            <h3>快速筛选</h3>
            <label>
              <span>案件来源</span>
              <select value="all" onChange={() => undefined}>
                <option value="all">全部来源</option>
              </select>
            </label>
            <label>
              <span>风险区域</span>
              <select value="all" onChange={() => undefined}>
                <option value="all">全部风险区域</option>
              </select>
            </label>
            <button className="btn-ghost-sm" type="button" onClick={() => setWorkflowFilter('all')}>重置筛选</button>
          </div>
        </aside>

        <main className="card sg-queue">
          <div className="card-head">
            <span className="ico">◆</span>
            <span className="ti">闭环研判队列</span>
            <span className="spacer" />
            <span className="chip accent">{visibleSuggestions.length} 项</span>
          </div>
          <div className="sg-status-tabs">
            <button className="on"><span>全部</span><b>{stats.total}</b></button>
            <button className="danger"><span>阻塞中</span><b>{stats.priority.high}</b></button>
            <button className="info"><span>进行中</span><b>{stats.priority.medium}</b></button>
            <button className="warn"><span>待处理</span><b>{stats.priority.low}</b></button>
            <button className="done"><span>已完成</span><b>{completedCount}</b></button>
          </div>
          <div className="sg-table-head">
            <span>优先级</span>
            <span>目标 / 案件编号</span>
            <span>待办类型</span>
            <span>阻塞原因 / 关键缺口</span>
            <span>当前阻塞点</span>
            <span>下一步安全动作</span>
            <span>状态</span>
            <span>更新时间</span>
          </div>
          <div className="card-body">
            {isLoading ? (
              <div className="empty-state" style={{ height: 300 }}>
                <div className="icon">⌛</div>
                <div>正在生成待办</div>
              </div>
            ) : visibleSuggestions.length === 0 ? (
              <div className="empty-state" style={{ height: 300 }}>
                <div className="icon">✓</div>
                <div>当前没有待处理待办</div>
                <span>案件、告警、会议、结论和报告质量均未触发当前分类待办。</span>
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
        </main>

        <aside className="card sg-detail">
          <div className="sg-detail-header">
            <div>
              <strong>{selectedSuggestion?.target_type === 'case' ? `AI${String(selectedSuggestion.target_id).padStart(4, '0')}` : selectedDetail.targetLabel}</strong>
              <span>{selectedDetail.targetLabel}</span>
            </div>
            <b>{selectedSuggestion ? (PRIORITY_META[selectedSuggestion.priority]?.label ?? selectedSuggestion.priority) : '未选择'}</b>
          </div>
          <div className="sg-detail-body">
            <div className="sg-blocker">
              <span>关键核算/研判阻塞</span>
              <strong>{selectedDetail.blocker}</strong>
              <small>请补齐事实依据或人工确认后再进入下一步。</small>
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
              disabled={!selectedSuggestion || actionBusy}
              onClick={() => selectedSuggestion && handleAction(selectedSuggestion)}
            >
              {selectedSuggestion ? (ACTION_LABELS[selectedSuggestion.action] ?? '处理') : '选择待办'}
            </button>
          </div>
        </aside>
      </section>

      <section className="sg-bottom-status">
        <div className="sg-batch-progress">
          <h3>批量研判进度</h3>
          <span>今日已审 {reviewedToday} / {Math.max(suggestions.length, 1)}</span>
          <div className="sg-progress"><i style={{ width: `${batchProgress}%` }} /></div>
          <b>{batchProgress}%</b>
        </div>
        <div className="sg-skip-reasons">
          <h3>失败 / 跳过原因（近 7 日）</h3>
          <span>材料缺失 {stats.type.bonus || 0}</span>
          <span>指标缺失 {filterSuggestionsByWorkflow(suggestions, 'bonus_metric_gap').length}</span>
          <span>坐标缺失 {filterSuggestionsByWorkflow(suggestions, 'coordinate_gap').length}</span>
          <span>其他 {stats.type.workflow || 0}</span>
        </div>
        <div className="sg-fallback-state">
          <h3>确定性兜底与回退状态</h3>
          <span>规则引擎 <b>正常</b></span>
          <span>ML 推理降级 <b>可用</b></span>
          <span>人工复核兜底 <b>已启用</b></span>
        </div>
      </section>
    </div>
  )
}

export default Suggestions
