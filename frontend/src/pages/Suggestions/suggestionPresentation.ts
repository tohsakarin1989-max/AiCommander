import type { WorkSuggestion } from '../../services/suggestions'

export const PRIORITY_META: Record<string, { label: string; cls: string }> = {
  high: { label: '高优先级', cls: 'high' },
  medium: { label: '中优先级', cls: 'medium' },
  low: { label: '低优先级', cls: 'low' },
}

export const ACTION_LABELS: Record<string, string> = {
  open_case: '查看案件',
  preprocess_case: '执行预处理',
  review_conclusion: '进入结论复核',
  convert_event_to_case: '转为案件',
  generate_conclusion_from_meeting: '打开研判包',
  open_analysis_package: '打开研判包',
  review_bonus_data: '进入奖金核算',
  review_bonus_materials: '进入奖金核算',
  open_alert_triage_pack: '打开研判包',
  review_experience_card: '复核经验卡',
  generate_experience_card: '生成经验卡',
  review_processing_card: '查看处理卡',
  review_prevention_reference: '查看防控参考',
}

export const TYPE_LABELS: Record<string, string> = {
  data_quality: '数据质量',
  analysis: '智能分析',
  review: '人工复核',
  workflow: '流程待办',
  bonus: '奖金核算',
  alert: '数智告警',
  experience: '经验卡',
  report_quality: '报告质量',
  processing_card: '案件处理卡',
}

export const SUGGESTION_FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'data_quality', label: TYPE_LABELS.data_quality },
  { value: 'analysis', label: TYPE_LABELS.analysis },
  { value: 'bonus', label: TYPE_LABELS.bonus },
  { value: 'alert', label: TYPE_LABELS.alert },
  { value: 'review', label: TYPE_LABELS.review },
  { value: 'experience', label: TYPE_LABELS.experience },
  { value: 'processing_card', label: TYPE_LABELS.processing_card },
  { value: 'report_quality', label: TYPE_LABELS.report_quality },
  { value: 'workflow', label: TYPE_LABELS.workflow },
]

export type SuggestionTypeFilter = (typeof SUGGESTION_FILTERS)[number]['value']

export function numericTargetId(suggestion: WorkSuggestion) {
  const value = typeof suggestion.target_id === 'number'
    ? suggestion.target_id
    : Number(suggestion.target_id)
  return Number.isFinite(value) ? value : null
}

export function buildSuggestionStats(suggestions: WorkSuggestion[]) {
  return suggestions.reduce(
    (acc, item) => {
      acc.total += 1
      acc.priority[item.priority] = (acc.priority[item.priority] || 0) + 1
      acc.type[item.type] = (acc.type[item.type] || 0) + 1
      return acc
    },
    {
      total: 0,
      priority: { high: 0, medium: 0, low: 0 } as Record<string, number>,
      type: {} as Record<string, number>,
    }
  )
}

export function filterSuggestions(suggestions: WorkSuggestion[], filter: SuggestionTypeFilter) {
  if (filter === 'all') return suggestions
  return suggestions.filter(item => item.type === filter)
}

export function getSuggestionRoute(suggestion: WorkSuggestion): string | null {
  const targetId = numericTargetId(suggestion)
  switch (suggestion.action) {
    case 'open_case':
    case 'review_processing_card':
      return targetId ? `/cases?caseId=${targetId}` : '/cases'
    case 'review_bonus_data':
    case 'review_bonus_materials':
      return targetId ? `/cases/bonus?caseId=${targetId}` : '/cases/bonus'
    case 'review_conclusion':
      return suggestion.target_id
        ? `/conclusions?conclusionId=${encodeURIComponent(String(suggestion.target_id))}`
        : '/conclusions'
    case 'generate_conclusion_from_meeting':
    case 'open_analysis_package':
      return `/reports?meetingId=${encodeURIComponent(String(suggestion.target_id))}`
    case 'open_alert_triage_pack':
      return targetId ? `/intelli-inspect?alertId=${targetId}` : '/intelli-inspect'
    case 'review_experience_card':
    case 'generate_experience_card':
      return targetId ? `/case-intelligence?caseId=${targetId}` : '/case-intelligence'
    case 'review_prevention_reference':
      return `/case-intelligence?area=${encodeURIComponent(String(suggestion.target_id))}`
    default:
      return null
  }
}
