import { describe, expect, it } from 'vitest'
import type { IntelligenceReport } from '../../services/caseIntelligence'
import { getReportDraftMeta, getReportMarkdown } from './caseIntelligencePresentation'

const report: IntelligenceReport = {
  title: '旧报告标题',
  generated_at: '2026-06-06T00:00:00Z',
  case_id: 12,
  days: 30,
  sections: [],
  markdown: '# 旧报告 Markdown',
  ai_output: {
    title: '标准化 AI 草稿',
    output_type: 'case_intelligence_report',
    draft_status: 'draft',
    review_status: 'pending_review',
    model_status: 'deterministic_fallback',
    generated_at: '2026-06-06T00:00:00Z',
    facts: ['事实'],
    inferences: [{ claim: '推断', basis: ['依据'], confidence: 'medium' }],
    recommendations: [{ title: '建议', action: '人工复核', basis: ['依据'], evidence: [], priority: 'medium' }],
    information_gaps: ['缺口'],
    evidence_refs: [{ id: 'case:AI2026-0001', kind: 'case', summary: '证据', basis: [] }],
    boundary: ['不替代人工复核'],
    markdown: '# 标准化 AI 草稿\n\n## 事实依据\n- 事实',
  },
}

describe('caseIntelligencePresentation', () => {
  it('prefers normalized ai output markdown for copyable reports', () => {
    expect(getReportMarkdown(report)).toBe(report.ai_output?.markdown)
    expect(getReportMarkdown({ ...report, ai_output: undefined })).toBe(report.markdown)
  })

  it('summarizes draft and review status for normalized reports', () => {
    expect(getReportDraftMeta(report)).toEqual({
      draftStatus: '草稿',
      reviewStatus: '待人工复核',
      modelStatus: '规则兜底',
    })
  })
})
