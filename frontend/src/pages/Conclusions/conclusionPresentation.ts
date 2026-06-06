import type { Conclusion, StructuredAiOutput } from '../../types'

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

function listBlock(items: string[] | undefined, emptyText: string): string {
  const rows = (items || []).map(item => item.trim()).filter(Boolean)
  if (rows.length === 0) return `- ${emptyText}`
  return rows.map(item => `- ${item}`).join('\n')
}

export function getConclusionAiOutput(conclusion?: Conclusion | null): StructuredAiOutput | undefined {
  return conclusion?.ai_output || conclusion?.evidence?.ai_output
}

export function getConclusionDraftMeta(conclusion?: Conclusion | null) {
  const output = getConclusionAiOutput(conclusion)
  const reviewStatus = conclusion?.review_status || output?.review_status ||
    (conclusion?.status === 'published' ? 'approved' : conclusion?.status === 'rejected' ? 'rejected' : conclusion?.status === 'flagged' ? 'flagged' : '')

  return {
    draftStatus: DRAFT_LABELS[conclusion?.draft_status || output?.draft_status || ''] ||
      conclusion?.draft_status || output?.draft_status || '草稿',
    reviewStatus: REVIEW_LABELS[reviewStatus || ''] || reviewStatus || '待人工复核',
    modelStatus: MODEL_LABELS[conclusion?.model_status || output?.model_status || ''] ||
      conclusion?.model_status || output?.model_status || '规则兜底',
  }
}

export function getConclusionMarkdown(conclusion?: Conclusion | null): string {
  if (!conclusion) return ''

  const normalizedMarkdown = getConclusionAiOutput(conclusion)?.markdown?.trim()
  if (normalizedMarkdown) return normalizedMarkdown

  return [
    `# 结论草稿：案件 #${conclusion.case_id}`,
    '',
    `- 结论 ID：${conclusion.id}`,
    `- 当前状态：${conclusion.status || '待人工复核'}`,
    `- 置信度：${typeof conclusion.confidence === 'number' ? `${Math.round(conclusion.confidence * 100)}%` : '待人工确认'}`,
    `- 风险等级：${conclusion.risk_level || '待人工确认'}`,
    '',
    '## 摘要',
    conclusion.summary || '暂无摘要',
    '',
    '## 事实依据',
    listBlock(conclusion.evidence?.key_evidence, '暂无事实依据，需人工补录'),
    '',
    '## 建议下一步',
    listBlock(conclusion.evidence?.recommendations, '暂无建议，需人工复核后补充'),
    '',
    '## 信息缺口',
    '- 未接入标准化 AI 输出，建议复核案件事实、证据来源和建议边界。',
    '',
    '## 边界说明',
    '- 该草稿仅用于涉油案件研判辅助，不替代人工审核、事实确认和处置决策。',
  ].join('\n')
}
