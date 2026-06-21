import { describe, expect, it } from 'vitest'
import type { Conclusion } from '../../types'
import { getConclusionDraftMeta, getConclusionMarkdown } from './conclusionPresentation'

describe('conclusionPresentation', () => {
  it('prefers normalized ai output markdown and review metadata', () => {
    const conclusion = {
      id: 9,
      case_id: 3,
      status: 'needs_review',
      confidence: 0.72,
      risk_level: 'medium',
      summary: '疑似夜间盗运链条。',
      draft_status: 'draft',
      review_status: 'pending_review',
      model_status: 'deterministic_fallback',
      ai_output: {
        title: '结论草稿',
        output_type: 'conclusion_draft',
        draft_status: 'draft',
        review_status: 'pending_review',
        model_status: 'deterministic_fallback',
        generated_at: '2026-06-06T00:00:00Z',
        facts: ['案件发生于夜间'],
        inferences: [],
        recommendations: [],
        information_gaps: [],
        evidence_refs: [{ id: 'case:3', kind: 'case', summary: '案件 #3' }],
        boundary: ['不替代人工审核'],
        markdown: '# 结论草稿\n\n## 事实依据\n- 案件发生于夜间\n\n## 证据索引\n- case:3：案件 #3',
      },
      created_at: '2026-06-06T00:00:00Z',
    } satisfies Conclusion

    expect(getConclusionMarkdown(conclusion)).toBe(conclusion.ai_output.markdown)
    expect(getConclusionDraftMeta(conclusion)).toEqual({
      draftStatus: '草稿',
      reviewStatus: '待人工复核',
      modelStatus: '规则兜底',
    })
  })

  it('builds a fallback markdown draft from legacy evidence fields', () => {
    const conclusion = {
      id: 10,
      case_id: 4,
      status: 'published',
      confidence: 0.91,
      risk_level: 'high',
      summary: '高风险区域反复出现同类作案条件。',
      evidence: {
        key_evidence: ['牙四公路夜间通行记录异常'],
        recommendations: ['补充调取沿线卡口记录'],
      },
      created_at: '2026-06-06T00:00:00Z',
    } satisfies Conclusion

    const markdown = getConclusionMarkdown(conclusion)

    expect(markdown).toContain('# 结论草稿：案件 #4')
    expect(markdown).toContain('## 事实依据')
    expect(markdown).toContain('- 牙四公路夜间通行记录异常')
    expect(markdown).toContain('## 建议下一步')
    expect(markdown).toContain('- 补充调取沿线卡口记录')
    expect(getConclusionDraftMeta(conclusion).reviewStatus).toBe('已确认')
  })
})
