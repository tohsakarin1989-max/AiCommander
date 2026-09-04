import { describe, expect, it } from 'vitest'
import type { IntelligenceReport } from '../../services/caseIntelligence'
import {
  getCaseDiagramSummary,
  getExperienceStatusMeta,
  getKnowledgeRoute,
  getKnowledgeSourceLabel,
  getReportDraftMeta,
  getReportMarkdown,
} from './caseIntelligencePresentation'

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

  it('labels knowledge assets and experience review status for the workbench', () => {
    expect(getKnowledgeSourceLabel('experience_card')).toBe('经验卡')
    expect(getKnowledgeSourceLabel('report')).toBe('分析报告')
    expect(getExperienceStatusMeta('confirmed')).toEqual({ label: '已入库', color: 'green' })
    expect(getExperienceStatusMeta('draft')).toEqual({ label: '草稿', color: 'default' })
  })

  it('summarizes one-case diagram data and keeps knowledge routes clickable', () => {
    expect(getCaseDiagramSummary({
      case_id: 12,
      nodes: [
        { id: 'case:12', type: 'case', label: '案件' },
        { id: 'evidence:1', type: 'evidence', label: '现场照片' },
      ],
      edges: [{ from: 'case:12', to: 'evidence:1', label: '证据' }],
      boundary: '只表达案件事实链路',
    })).toBe('包含 2 个节点、1 条关系')

    expect(getKnowledgeRoute({
      source_type: 'report',
      source_id: 3,
      title: '报告',
      snippet: '引用',
      score: 12,
      route: '/reports?reportId=3',
      evidence_refs: [],
    })).toBe('/reports?reportId=3')
  })
})
