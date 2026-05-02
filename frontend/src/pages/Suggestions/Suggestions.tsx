import { useMemo } from 'react'
import { message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { caseApi } from '../../services/cases'
import { eventApi } from '../../services/events'
import { suggestionsApi, type WorkSuggestion } from '../../services/suggestions'
import './Suggestions.css'

const PRIORITY_META: Record<string, { label: string; cls: string }> = {
  high: { label: '高优先级', cls: 'high' },
  medium: { label: '中优先级', cls: 'medium' },
  low: { label: '低优先级', cls: 'low' },
}

const ACTION_LABELS: Record<string, string> = {
  open_case: '查看案件',
  preprocess_case: '执行预处理',
  review_conclusion: '审核结论',
  convert_event_to_case: '转为案件',
  generate_conclusion_from_meeting: '生成结论',
  create_patrol: '生成巡逻',
}

const TYPE_LABELS: Record<string, string> = {
  data_quality: '数据质量',
  analysis: '智能分析',
  review: '人工审核',
  workflow: '流程推进',
  patrol: '巡逻部署',
}

function numericTargetId(suggestion: WorkSuggestion) {
  const value = typeof suggestion.target_id === 'number'
    ? suggestion.target_id
    : Number(suggestion.target_id)
  return Number.isFinite(value) ? value : null
}

const Suggestions: React.FC = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

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
  const stats = useMemo(() => {
    return suggestions.reduce(
      (acc, item) => {
        acc.total += 1
        acc[item.priority] += 1
        return acc
      },
      { total: 0, high: 0, medium: 0, low: 0 } as Record<string, number>
    )
  }, [suggestions])

  const handleAction = (suggestion: WorkSuggestion) => {
    const targetId = numericTargetId(suggestion)
    switch (suggestion.action) {
      case 'open_case':
        if (targetId) navigate(`/cases?caseId=${targetId}`)
        break
      case 'preprocess_case':
        if (targetId) preprocessMutation.mutate(targetId)
        break
      case 'review_conclusion':
        navigate('/conclusions')
        break
      case 'convert_event_to_case':
        if (targetId) convertEventMutation.mutate(targetId)
        break
      case 'generate_conclusion_from_meeting':
        navigate(`/conclusions?meetingId=${encodeURIComponent(String(suggestion.target_id))}`)
        break
      case 'create_patrol':
        navigate(`/patrols?area=${encodeURIComponent(String(suggestion.target_id))}`)
        break
      default:
        message.info('该建议暂未配置自动动作')
    }
  }

  const actionBusy = preprocessMutation.isPending || convertEventMutation.isPending

  return (
    <div className="page suggestions-page">
      <div className="page-title">
        <h1>建议中心</h1>
        <span className="sub">跨模块待办 · 数据质量 · 研判流程 · 巡逻部署</span>
      </div>

      <div className="sg-stats">
        <div className="sg-stat"><span>待处理</span><b>{stats.total}</b></div>
        <div className="sg-stat high"><span>高优先级</span><b>{stats.high}</b></div>
        <div className="sg-stat medium"><span>中优先级</span><b>{stats.medium}</b></div>
        <div className="sg-stat low"><span>低优先级</span><b>{stats.low}</b></div>
      </div>

      <div className="card">
        <div className="card-head">
          <span className="ico">◎</span>
          <span className="ti">智能工作队列</span>
          <span className="spacer" />
          <span className="chip accent">
            {data ? `生成于 ${dayjs(data.generated_at).format('HH:mm:ss')}` : '自动刷新'}
          </span>
        </div>
        <div className="card-body">
          {isLoading ? (
            <div className="empty-state" style={{ height: 260 }}>
              <div className="icon">⌛</div>
              <div>正在生成建议</div>
            </div>
          ) : suggestions.length === 0 ? (
            <div className="empty-state" style={{ height: 260 }}>
              <div className="icon">✓</div>
              <div>当前没有待处理建议</div>
              <span>案件、事件、会议、结论和巡逻风险均未触发开放待办。</span>
            </div>
          ) : (
            <div className="sg-list">
              {suggestions.map((suggestion) => {
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
