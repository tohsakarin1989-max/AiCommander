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
  SUGGESTION_FILTERS,
  TYPE_LABELS,
  buildSuggestionStats,
  filterSuggestions,
  getSuggestionRoute,
  numericTargetId,
  type SuggestionTypeFilter,
} from './suggestionPresentation'
import './Suggestions.css'

const Suggestions: React.FC = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [typeFilter, setTypeFilter] = useState<SuggestionTypeFilter>('all')

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
  const visibleSuggestions = useMemo(() => filterSuggestions(suggestions, typeFilter), [suggestions, typeFilter])
  const stats = useMemo(() => buildSuggestionStats(suggestions), [suggestions])

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
    <div className="page suggestions-page">
      <div className="page-title">
        <h1>待办中心</h1>
        <span className="sub">统一收纳研判相关待办 · 案件缺口 · 数智告警 · 结论复核 · 报告质量 · 经验沉淀</span>
      </div>

      <div className="sg-stats">
        <div className="sg-stat"><span>待处理</span><b>{stats.total}</b></div>
        <div className="sg-stat high"><span>高优先级</span><b>{stats.priority.high}</b></div>
        <div className="sg-stat medium"><span>中优先级</span><b>{stats.priority.medium}</b></div>
        <div className="sg-stat low"><span>低优先级</span><b>{stats.priority.low}</b></div>
      </div>

      <div className="card">
        <div className="card-head">
          <span className="ico">◎</span>
          <span className="ti">研判工作队列</span>
          <span className="spacer" />
          <span className="chip accent">
            {data ? `生成于 ${dayjs(data.generated_at).format('HH:mm:ss')}` : '自动刷新'}
          </span>
        </div>
        <div className="sg-filter-row">
          {SUGGESTION_FILTERS.map(filter => (
            <button
              key={filter.value}
              className={`sg-filter${typeFilter === filter.value ? ' on' : ''}`}
              onClick={() => setTypeFilter(filter.value)}
            >
              {filter.label}
              {filter.value !== 'all' && <span>{stats.type[filter.value] || 0}</span>}
            </button>
          ))}
        </div>
        <div className="card-body">
          {isLoading ? (
            <div className="empty-state" style={{ height: 260 }}>
              <div className="icon">⌛</div>
              <div>正在生成待办</div>
            </div>
          ) : visibleSuggestions.length === 0 ? (
            <div className="empty-state" style={{ height: 260 }}>
              <div className="icon">✓</div>
              <div>当前没有待处理待办</div>
              <span>案件、告警、会议、结论和报告质量均未触发当前分类待办。</span>
            </div>
          ) : (
            <div className="sg-list">
              {visibleSuggestions.map((suggestion) => {
                const priority = PRIORITY_META[suggestion.priority] ?? PRIORITY_META.medium
                return (
                  <div key={suggestion.id} className={`sg-item ${priority.cls}`}>
                    <div className="sg-item-main">
                      <div className="sg-item-kicker">
                        <span>{TYPE_LABELS[suggestion.type] ?? suggestion.type}</span>
                        <span>{priority.label}</span>
                        <span>{dayjs(suggestion.created_at).format('MM-DD HH:mm')}</span>
                      </div>
                      <div className="sg-item-title">{suggestion.title}</div>
                      <div className="sg-item-desc">{suggestion.description}</div>
                    </div>
                    <div className="sg-item-side">
                      <span className="sg-target">{suggestion.target_type}:{String(suggestion.target_id)}</span>
                      <button
                        className="btn-primary"
                        disabled={actionBusy}
                        onClick={() => handleAction(suggestion)}
                      >
                        {ACTION_LABELS[suggestion.action] ?? '处理'}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default Suggestions
