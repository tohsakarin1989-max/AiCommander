import type { UserRole } from '../../services/auth'

const STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  planning: '规划中',
  running: '执行中',
  waiting_approval: '等待人工复核',
  verifying: '验证中',
  completed: '已完成',
  degraded: '降级完成',
  failed: '失败',
  cancelled: '已取消',
  expired: '审批已过期',
}

const EVENT_LABELS: Record<string, string> = {
  run_created: '任务已创建',
  planning_started: '开始规划工具步骤',
  run_started: '开始执行',
  tool_completed: '业务工具完成',
  verification_started: '开始验证证据',
  model_completed: '脱敏模型归纳完成',
  model_degraded: '模型不可用，使用规则结果',
  approval_required: '等待人工审批',
  approval_decided: '审批决定已记录',
  approval_expired: '候选审批已过期',
  run_completed: '任务已完成',
  run_failed: '任务失败',
  run_cancelled: '任务已取消',
  run_expired: '任务审批窗口已过期',
  dispatch_failed: '独立队列不可用',
  pilot_suspended: '试用已停用，任务安全终止',
  case_pilot_suspended: '案件试用已停用，任务安全终止',
  dual_domain_pilot_suspended: '双域试用已停用，任务安全终止',
}

const EXECUTION_MODE_LABELS: Record<string, string> = {
  deterministic: '内网规则引擎',
  agent_lab: '脱敏模型辅助',
  deterministic_fallback: '模型降级，内网规则接管',
}

const PROVIDER_LABELS: Record<string, string> = {
  deterministic: '内网规则引擎',
  openai_agents: 'OpenAI Agents（可选）',
  openai: 'OpenAI（可选）',
  'openai-compatible': '兼容模型网关',
  'azure-openai': 'Azure OpenAI（可选）',
  anthropic: 'Anthropic（可选）',
  claude: 'Anthropic（可选）',
  model_registry: '系统模型注册表',
}

export function agentStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? '未知状态'
}

export function agentEventLabel(eventType: string): string {
  return EVENT_LABELS[eventType] ?? eventType
}

export function agentExecutionModeLabel(mode: string | undefined): string {
  if (!mode) return '等待执行'
  return EXECUTION_MODE_LABELS[mode] ?? '受控执行'
}

export function agentProviderLabel(provider: string | undefined): string {
  if (!provider) return '未配置'
  return PROVIDER_LABELS[provider] ?? provider
}

export function formatAgentDuration(durationMs: number | null | undefined): string {
  if (durationMs == null) return '—'
  if (durationMs < 1000) return `${Math.max(0, Math.round(durationMs))}毫秒`
  return `${(Math.max(0, durationMs) / 1000).toFixed(1)}秒`
}

export function formatAgentCost(costUsd: number | null | undefined): string {
  const normalized = Number.isFinite(costUsd) ? Math.max(0, Number(costUsd)) : 0
  return `US$${normalized.toFixed(4)}`
}

export function canReviewAgentRun(role: UserRole | undefined): boolean {
  return role === 'admin'
}

export function evidenceCoverage(conclusionsWithEvidence: number, conclusionCount: number): number {
  if (conclusionCount <= 0) return 0
  return Math.round(Math.min(1, Math.max(0, conclusionsWithEvidence / conclusionCount)) * 100)
}

export function isAgentRunActive(status: string): boolean {
  return ['queued', 'planning', 'running', 'verifying'].includes(status)
}

export function agentErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) return error.message
  if (typeof error === 'object' && error !== null) {
    const candidate = error as { message?: unknown; detail?: unknown }
    if (typeof candidate.message === 'string' && candidate.message.trim()) return candidate.message
    if (typeof candidate.detail === 'string' && candidate.detail.trim()) return candidate.detail
  }
  return fallback
}

export function agentResultText(item: unknown): string {
  if (typeof item === 'string') return item
  if (!item || typeof item !== 'object' || Array.isArray(item)) return String(item ?? '')
  const value = item as Record<string, unknown>
  if (typeof value.message === 'string') {
    return value.message
  }
  if (value.case_id != null && value.historical_frequency && typeof value.historical_frequency === 'object') {
    const history = value.historical_frequency as Record<string, unknown>
    const tags = Array.isArray(value.modus_tags) && value.modus_tags.length
      ? `｜手法标签 ${value.modus_tags.join('、')}`
      : '｜手法标签待补充'
    return `案件证据 #${value.case_id}｜风险条件强度 ${value.risk_score ?? 0}｜${history.days ?? '-'}天/${history.radius_km ?? '-'}公里内历史记录 ${history.case_count ?? 0} 条${tags}`
  }
  if (value.case_id != null && value.asset_id != null && value.distance_km != null) {
    return `案件证据 #${value.case_id}｜地图证据 #${value.asset_id}｜距离 ${value.distance_km} 公里｜${value.basis ?? '所选范围内空间条件'}`
  }
  if (value.asset_id != null && value.historical_case_count != null) {
    return `地图证据 #${value.asset_id}｜${value.radius_km ?? '-'} 公里内历史案件 ${value.historical_case_count} 起｜${value.label ?? '历史聚合，待人工复核'}`
  }
  if (value.case_id != null && value.quality_score != null) {
    return `案件证据 #${value.case_id}｜质量分 ${value.quality_score}（${value.quality_level ?? '待评估'}）｜缺项 ${value.missing_count ?? 0}｜提醒 ${value.warning_count ?? 0}`
  }
  if (value.asset_id != null) {
    return `地图证据 #${value.asset_id}｜${value.asset_type ?? '未分类'}｜来源 ${value.source ?? '未记录'}｜${value.has_coordinates ? '坐标已填' : '坐标缺失'}｜${value.verified ? '已核验' : '待核验'}`
  }
  const scalarParts = Object.entries(value)
    .filter(([, child]) => ['string', 'number', 'boolean'].includes(typeof child))
    .slice(0, 5)
    .map(([key, child]) => `${key}: ${String(child)}`)
  return scalarParts.length ? scalarParts.join('｜') : '已形成一条结构化证据项'
}
