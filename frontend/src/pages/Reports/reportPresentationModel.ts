type UnknownRecord = Record<string, unknown>

export interface ReportPresentation {
  summary: string
  conclusions: string
  consensusPoints: string[]
  disagreementPoints: string[]
  keyInsights: string[]
  areaRisks: string[]
  chainCorrelations: string[]
  actionSuggestions: string[]
  experienceCards: string[]
  modelContributions: Array<{ model: string; contribution: string }>
}

export interface ReportReviewPresentation {
  totalFindings: number
  severityCounts: Record<string, number>
  findingLines: string[]
  suggestedFixes: string[]
  manualReviewRequired: boolean
}

const EMPTY_TEXT = '暂无'

function isRecord(value: unknown): value is UnknownRecord {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function toText(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(toText).filter(Boolean).join('；')
  if (!isRecord(value)) return ''

  const label = [
    value.type,
    value.area_name,
    value.location,
    value.target,
    value.description,
    value.rationale,
    value.implication,
    value.action_required,
  ].map(toText).filter(Boolean)

  if (label.length > 0) return label.join('：')
  return JSON.stringify(value)
}

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map(toText).map(item => item.trim()).filter(Boolean)
}

function normalizeContent(raw: unknown): UnknownRecord {
  if (isRecord(raw)) return raw
  if (typeof raw !== 'string') return {}

  try {
    const parsed = JSON.parse(raw)
    return isRecord(parsed) ? parsed : {}
  } catch {
    return { summary: raw }
  }
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const text = toText(value)
    if (text) return text
  }
  return EMPTY_TEXT
}

function formatPatternConsensus(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    if (!isRecord(item)) return toText(item)
    const title = firstText(item.type, '规律共识')
    const detail = firstText(item.description)
    const confidence = firstText(item.confidence)
    const supporting = firstText(item.supporting_experts)
    const suffix = [
      confidence && confidence !== EMPTY_TEXT ? `置信度：${confidence}` : '',
      supporting && supporting !== EMPTY_TEXT ? `支持模型：${supporting}` : '',
    ].filter(Boolean).join('，')
    return suffix ? `${title}：${detail}（${suffix}）` : `${title}：${detail}`
  }).filter(Boolean)
}

function formatAreaRisks(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    if (!isRecord(item)) return toText(item)
    const name = firstText(item.area_name, item.location, '风险区域')
    const level = firstText(item.risk_level)
    const rank = firstText(item.priority_rank)
    const factors = toStringList(item.risk_factors ?? item.reasons)
    const head = [
      name,
      level && level !== EMPTY_TEXT ? `风险：${level}` : '',
      rank && rank !== EMPTY_TEXT ? `优先级：${rank}` : '',
    ].filter(Boolean).join('，')
    return factors.length > 0 ? `${head}。依据：${factors.join('；')}` : head
  }).filter(Boolean)
}

function formatCorrelations(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    if (!isRecord(item)) return toText(item)
    const description = firstText(item.description, item.reasoning)
    const implication = firstText(item.implication)
    const action = firstText(item.action_required)
    return [
      description,
      implication && implication !== EMPTY_TEXT ? `研判意义：${implication}` : '',
      action && action !== EMPTY_TEXT ? `建议动作：${action}` : '',
    ].filter(Boolean).join('；')
  }).filter(Boolean)
}

function formatPatrolPlan(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    if (!isRecord(item)) return toText(item)
    const priority = firstText(item.priority)
    const location = firstText(item.location, item.area)
    const timing = firstText(item.timing)
    const focus = toStringList(item.focus ?? item.focus_on)
    const method = firstText(item.method)
    return [
      priority && priority !== EMPTY_TEXT ? `优先级${priority}` : '',
      location,
      timing && timing !== EMPTY_TEXT ? `时段：${timing}` : '',
      focus.length > 0 ? `重点：${focus.join('；')}` : '',
      method && method !== EMPTY_TEXT ? `方式：${method}` : '',
    ].filter(Boolean).join('，')
  }).filter(Boolean)
}

function formatSearchPriorities(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    if (!isRecord(item)) return toText(item)
    const target = firstText(item.target)
    const area = firstText(item.area)
    const rationale = firstText(item.rationale, item.method)
    return [
      target,
      area && area !== EMPTY_TEXT ? `区域：${area}` : '',
      rationale && rationale !== EMPTY_TEXT ? `依据/方法：${rationale}` : '',
    ].filter(Boolean).join('，')
  }).filter(Boolean)
}

function formatContributions(value: unknown): Array<{ model: string; contribution: string }> {
  if (!isRecord(value)) return []
  return Object.entries(value)
    .map(([model, contribution]) => ({ model, contribution: toText(contribution) }))
    .filter(item => item.contribution)
}

function mergeUnique(...groups: string[][]): string[] {
  const seen = new Set<string>()
  return groups.flat().filter((item) => {
    const key = item.trim()
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function buildReportPresentation(report: unknown): ReportPresentation {
  const record = isRecord(report) ? report : {}
  const content = normalizeContent(record.content)
  const consensusPoints = mergeUnique(
    toStringList(record.consensus_points),
    toStringList(content.consensus_points),
    formatPatternConsensus(content.patterns_consensus),
  )
  const disagreementPoints = mergeUnique(
    toStringList(record.disagreement_points),
    toStringList(content.disagreement_points),
  )
  const areaRisks = formatAreaRisks(content.area_risk_assessment ?? content.area_risks)
  const chainCorrelations = formatCorrelations(content.key_correlations ?? content.correlations)
  const patrolPlans = formatPatrolPlan(content.patrol_action_plan ?? content.patrol_suggestions)
  const searchPriorities = formatSearchPriorities(content.search_priorities ?? content.search_suggestions)
  const actionSuggestions = mergeUnique(
    toStringList(record.recommendations),
    toStringList(content.recommendations),
    toStringList(content.next_steps),
    patrolPlans,
    searchPriorities,
  )

  return {
    summary: firstText(content.summary, record.summary),
    conclusions: firstText(content.conclusions, content.ranking_summary, content.risk_trend),
    consensusPoints,
    disagreementPoints,
    keyInsights: mergeUnique(
      toStringList(content.top_ranked_insights),
      toStringList(content.experience_extraction),
    ),
    areaRisks,
    chainCorrelations,
    actionSuggestions,
    experienceCards: mergeUnique(toStringList(content.experience_extraction)),
    modelContributions: formatContributions(
      content.model_contributions ?? content.expert_contributions ?? record.model_contributions,
    ),
  }
}

const DRAFT_LABELS: Record<string, string> = {
  draft: '草稿',
}

const REVIEW_LABELS: Record<string, string> = {
  pending_review: '待人工复核',
  approved: '已确认',
  rejected: '已退回',
  flagged: '已标记',
}

const MODEL_LABELS: Record<string, string> = {
  deterministic_fallback: '规则兜底',
  llm_success: '模型生成',
  llm_failed: '模型失败',
}

export function getReportDraftMeta(report: unknown) {
  const record = isRecord(report) ? report : {}
  const output = isRecord(record.ai_output) ? record.ai_output : {}
  return {
    draftStatus: DRAFT_LABELS[toText(output.draft_status)] || toText(output.draft_status) || '草稿',
    reviewStatus: REVIEW_LABELS[toText(output.review_status)] || toText(output.review_status) || '待人工复核',
    modelStatus: MODEL_LABELS[toText(output.model_status)] || toText(output.model_status) || '规则兜底',
  }
}

export function getReportExportMarkdown(meetingId: string, report: unknown, exportedAt?: string): string {
  const record = isRecord(report) ? report : {}
  const output = isRecord(record.ai_output) ? record.ai_output : {}
  const normalizedMarkdown = toText(output.markdown)
  if (normalizedMarkdown) return normalizedMarkdown

  const presentation = buildReportPresentation(report)
  const toList = (items?: string[]) =>
    items && items.length > 0 ? items.map((item) => `- ${item}`).join('\n') : '- 暂无'
  const toContributionList = (items: Array<{ model: string; contribution: string }>) =>
    items.length > 0
      ? items.map((item) => `- ${item.model}：${item.contribution}`).join('\n')
      : '- 暂无'

  return [
    '# AI 圆桌研判报告',
    '',
    `- 会议编号：${meetingId}`,
    exportedAt ? `- 导出时间：${exportedAt}` : '',
    '',
    '## 执行摘要',
    presentation.summary,
    '',
    '## 综合结论',
    presentation.conclusions,
    '',
    '## 共识点',
    toList(presentation.consensusPoints),
    '',
    '## 分歧点',
    toList(presentation.disagreementPoints),
    '',
    '## 风险区域',
    toList(presentation.areaRisks),
    '',
    '## 链条关系',
    toList(presentation.chainCorrelations),
    '',
    '## 行动建议',
    toList(presentation.actionSuggestions),
    '',
    '## 经验沉淀',
    toList(presentation.experienceCards),
    '',
    '## 模型贡献',
    toContributionList(presentation.modelContributions),
    '',
  ].filter((line) => line !== '').join('\n')
}

export function buildReportReviewPresentation(review: unknown): ReportReviewPresentation {
  const record = isRecord(review) ? review : {}
  const findings = Array.isArray(record.findings) ? record.findings : []
  const severityCounts: Record<string, number> = {}
  const findingLines = findings
    .map((item) => {
      if (!isRecord(item)) return toText(item)
      const severity = toText(item.severity) || 'info'
      severityCounts[severity] = (severityCounts[severity] || 0) + 1
      const type = toText(item.type) || '问题'
      const message = toText(item.message) || '需人工复核'
      return `${severity} · ${type}：${message}`
    })
    .filter(Boolean)

  return {
    totalFindings: findingLines.length,
    severityCounts,
    findingLines,
    suggestedFixes: toStringList(record.suggested_fixes),
    manualReviewRequired: record.manual_review_required !== false,
  }
}
