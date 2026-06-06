import type { IntelligenceReport } from '../../services/caseIntelligence'

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
