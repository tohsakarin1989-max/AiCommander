import type { SuggestionWorkflow, WorkSuggestion } from '../../services/suggestions'

export const PRIORITY_META: Record<string, { label: string; cls: string }> = {
  high: { label: '高优先级', cls: 'high' },
  medium: { label: '中优先级', cls: 'medium' },
  low: { label: '低优先级', cls: 'low' },
}

export const ACTION_LABELS: Record<string, string> = {
  open_case: '查看案件',
  preprocess_case: '查看后台分析状态',
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

export const WORKFLOW_FILTERS = [
  { value: 'all', label: '全部待办' },
  { value: 'coordinate_gap', label: '坐标缺口' },
  { value: 'data_quality', label: '资料与分析状态' },
  { value: 'processing_card', label: '案件处理卡' },
  { value: 'bonus_metric_gap', label: '奖金核算指标缺口' },
  { value: 'bonus_material_gap', label: '佐证材料缺口' },
  { value: 'alert', label: '数智告警' },
  { value: 'conclusion_review', label: '结论复核' },
  { value: 'report_followup', label: '已有报告事项' },
  { value: 'experience', label: '经验卡确认' },
  { value: 'event_review', label: '独立事件' },
  { value: 'area_reference', label: '区域参考' },
] as const

export type SuggestionWorkflowFilter = SuggestionWorkflow

export interface SuggestionDetailPanel {
  targetLabel: string
  blocker: string
  facts: string[]
  inferences: string[]
  suggestions: string[]
  boundary: string
}

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

function includesAny(text: string, words: string[]) {
  return words.some(word => text.includes(word))
}

export function getSuggestionWorkflowBucket(suggestion: WorkSuggestion): Exclude<SuggestionWorkflowFilter, 'all'> {
  if (suggestion.workflow && WORKFLOW_FILTERS.some(item => item.value === suggestion.workflow)) return suggestion.workflow
  if (suggestion.type === 'processing_card') return 'processing_card'
  if (suggestion.target_type === 'event') return 'event_review'
  if (suggestion.target_type === 'area') return 'area_reference'
  const text = `${suggestion.title} ${suggestion.description} ${suggestion.action} ${suggestion.type}`
  if (includesAny(text, ['坐标', '经纬度', '点位'])) return 'coordinate_gap'
  if (suggestion.action === 'preprocess_case' || includesAny(text, ['预处理', '结构化', '清洗'])) return 'data_quality'
  if (suggestion.type === 'bonus' && (suggestion.action === 'review_bonus_data' || includesAny(text, ['指标', '车辆考核', '人员处理', '核算字段']))) return 'bonus_metric_gap'
  if (suggestion.type === 'bonus' && (suggestion.action === 'review_bonus_materials' || includesAny(text, ['材料', '单据', '佐证', '凭证']))) return 'bonus_material_gap'
  if (suggestion.type === 'alert' || suggestion.action === 'open_alert_triage_pack') return 'alert'
  if (suggestion.action === 'review_conclusion' || suggestion.type === 'review') return 'conclusion_review'
  if (suggestion.type === 'report_quality' || includesAny(text, ['报告', '沉淀', '会议'])) return 'report_followup'
  if (suggestion.type === 'experience' || includesAny(text, ['经验卡'])) return 'experience'
  return 'data_quality'
}

export function filterSuggestionsByWorkflow(suggestions: WorkSuggestion[], filter: SuggestionWorkflowFilter) {
  if (filter === 'all') return suggestions
  return suggestions.filter(item => getSuggestionWorkflowBucket(item) === filter)
}

export function buildSuggestionDetail(suggestion: WorkSuggestion | null | undefined): SuggestionDetailPanel {
  if (!suggestion) {
    return {
      targetLabel: '-',
      blocker: '未选择待办',
      facts: ['请从中间队列选择一条待办。'],
      inferences: ['系统不会在未选择待办时生成业务判断。'],
      suggestions: ['先按优先级处理阻塞项。'],
      boundary: '仅供人工复核，不自动认定，不自动派发执行任务。',
    }
  }

  const actionLabel = ACTION_LABELS[suggestion.action] ?? '人工处理'
  const typeLabel = TYPE_LABELS[suggestion.type] ?? suggestion.type
  const priorityLabel = PRIORITY_META[suggestion.priority]?.label ?? suggestion.priority
  const targetLabel = `${suggestion.target_type}:${String(suggestion.target_id)}`

  return {
    targetLabel,
    blocker: suggestion.title,
    facts: [
      `${typeLabel}待办：${suggestion.title}`,
      `目标对象：${targetLabel}`,
      suggestion.description,
    ].filter(Boolean),
    inferences: [
      `${priorityLabel}是待判断事项的排序提示，不代表案件严重程度或办结状态。`,
      suggestion.type === 'bonus'
        ? '奖金核算相关缺口只作为案件内业核算门禁，不进入指挥大屏明细展示。'
        : '这里只判断已有资料或成果；不要求每起案件都形成经验卡或报告。',
    ],
    suggestions: [
      `下一步安全动作：${actionLabel}`,
      '可先正常使用案件；仅在需要时补充资料、判断已有成果或导出报告。',
    ],
    boundary: '仅供人工复核，不自动认定，不自动派发执行任务。',
  }
}

export function getSuggestionRoute(suggestion: WorkSuggestion): string | null {
  const targetId = numericTargetId(suggestion)
  switch (suggestion.action) {
    case 'open_case':
    case 'preprocess_case':
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
      return targetId ? `/case-intelligence?caseId=${targetId}&tool=experience` : '/case-intelligence'
    case 'generate_experience_card':
      return targetId ? `/case-intelligence?caseId=${targetId}` : '/case-intelligence'
    case 'review_prevention_reference':
      return `/case-intelligence?area=${encodeURIComponent(String(suggestion.target_id))}`
    default:
      return null
  }
}
