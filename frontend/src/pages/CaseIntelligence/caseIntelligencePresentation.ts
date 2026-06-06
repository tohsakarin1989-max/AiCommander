import type { IntelligenceReport } from '../../services/caseIntelligence'
import type { CaseDiagram, KnowledgeSearchResult } from '../../types'

const DRAFT_LABELS: Record<string, string> = {
  draft: '草稿',
}

const REVIEW_LABELS: Record<string, string> = {
  pending_review: '待人工复核',
  approved: '已确认',
  rejected: '已退回',
}

const MODEL_LABELS: Record<string, string> = {
  deterministic_fallback: '规则兜底',
  llm_success: '模型生成',
  llm_failed: '模型失败',
}

export function getReportMarkdown(report?: IntelligenceReport | null): string {
  return report?.ai_output?.markdown || report?.markdown || ''
}

export function getReportDraftMeta(report?: IntelligenceReport | null) {
  const output = report?.ai_output
  return {
    draftStatus: DRAFT_LABELS[output?.draft_status || ''] || output?.draft_status || '草稿',
    reviewStatus: REVIEW_LABELS[output?.review_status || ''] || output?.review_status || '待人工复核',
    modelStatus: MODEL_LABELS[output?.model_status || ''] || output?.model_status || '规则兜底',
  }
}

const KNOWLEDGE_SOURCE_LABELS: Record<string, string> = {
  case_profile: '案件画像',
  experience_card: '经验卡',
  report: '分析报告',
  conclusion: '情报结论',
  alert: '告警',
  quality_gap: '质量缺口',
}

const EXPERIENCE_STATUS_LABELS: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  pending: { label: '待确认', color: 'gold' },
  pending_review: { label: '待确认', color: 'gold' },
  confirmed: { label: '已入库', color: 'green' },
  approved: { label: '已入库', color: 'green' },
  archived: { label: '已归档', color: 'default' },
}

export function getKnowledgeSourceLabel(sourceType?: string): string {
  if (!sourceType) return '知识来源'
  return KNOWLEDGE_SOURCE_LABELS[sourceType] || sourceType
}

export function getExperienceStatusMeta(status?: unknown): { label: string; color: string } {
  const key = typeof status === 'string' ? status : ''
  return EXPERIENCE_STATUS_LABELS[key] || { label: key || '待确认', color: 'gold' }
}

export function getCaseDiagramSummary(diagram?: CaseDiagram | null): string {
  if (!diagram) return '暂无一案一图数据'
  return `包含 ${diagram.nodes.length} 个节点、${diagram.edges.length} 条关系`
}

export function getKnowledgeRoute(result: KnowledgeSearchResult): string {
  return result.route || (result.source_type === 'experience_card' ? `/case-intelligence?caseId=${result.source_id}` : '')
}
