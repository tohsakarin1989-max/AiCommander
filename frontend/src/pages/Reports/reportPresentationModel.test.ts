import { describe, expect, it } from 'vitest'
import {
  buildReportPresentation,
  buildReportReviewPresentation,
  getReportDraftMeta,
  getReportExportMarkdown,
} from './reportPresentationModel'

describe('reportPresentationModel', () => {
  it('maps new structured meeting reports into visible detail sections', () => {
    const report = {
      content: {
        summary: '涉油违法犯罪呈现双层结构。',
        patterns_consensus: [
          {
            type: '时间规律',
            description: '年末年初夜间高发。',
            confidence: 'high',
            supporting_experts: 2,
          },
        ],
        area_risk_assessment: [
          {
            area_name: '双榆树村树林带',
            risk_level: 'high',
            risk_factors: ['隐蔽', '临近道路'],
            priority_rank: 1,
          },
        ],
        key_correlations: [
          {
            description: '大庆至大安存在转运链条。',
            implication: '提示跨区域联动。',
            action_required: '加强牙四公路设卡。',
          },
        ],
        patrol_action_plan: [
          {
            priority: 1,
            location: '牙四公路',
            timing: '22:00-05:00',
            focus: ['改装罐车'],
            method: '车巡+设卡',
          },
        ],
        next_steps: ['纳入专项打击方案。'],
        experience_extraction: ['源头、通道、窝点一体研判。'],
        expert_contributions: {
          research_1: '提炼盗运储模式。',
        },
      },
      consensus_points: [],
      disagreement_points: [],
      model_contributions: {},
    }

    const presentation = buildReportPresentation(report)

    expect(presentation.summary).toBe('涉油违法犯罪呈现双层结构。')
    expect(presentation.consensusPoints[0]).toContain('时间规律')
    expect(presentation.areaRisks[0]).toContain('双榆树村树林带')
    expect(presentation.chainCorrelations[0]).toContain('大庆至大安')
    expect(presentation.actionSuggestions).toEqual(
      expect.arrayContaining([
        expect.stringContaining('牙四公路'),
        '纳入专项打击方案。',
      ]),
    )
    expect(presentation.keyInsights).toEqual(
      expect.arrayContaining([
        '源头、通道、窝点一体研判。',
      ]),
    )
    expect(presentation.chainCorrelations[0]).toContain('跨区域联动')
    expect(presentation.modelContributions[0]).toEqual({
      model: 'research_1',
      contribution: '提炼盗运储模式。',
    })
  })

  it('keeps old report fields compatible', () => {
    const presentation = buildReportPresentation({
      summary: '旧报告摘要',
      content: {
        conclusions: '旧报告结论',
        recommendations: ['建议一'],
      },
      consensus_points: ['共识一'],
      disagreement_points: ['分歧一'],
      model_contributions: { model_a: '贡献一' },
    })

    expect(presentation.summary).toBe('旧报告摘要')
    expect(presentation.conclusions).toBe('旧报告结论')
    expect(presentation.consensusPoints).toEqual(['共识一'])
    expect(presentation.disagreementPoints).toEqual(['分歧一'])
    expect(presentation.actionSuggestions).toEqual(['建议一'])
    expect(presentation.modelContributions).toEqual([{ model: 'model_a', contribution: '贡献一' }])
  })

  it('prefers normalized ai output markdown and review metadata for report export', () => {
    const report = {
      content: { summary: '旧摘要' },
      ai_output: {
        title: '标准报告草稿',
        output_type: 'meeting_report_draft',
        draft_status: 'draft',
        review_status: 'pending_review',
        model_status: 'deterministic_fallback',
        generated_at: '2026-06-06T00:00:00Z',
        facts: ['事实'],
        inferences: [],
        recommendations: [],
        information_gaps: [],
        evidence_refs: [],
        boundary: [],
        markdown: '# 标准报告草稿\n\n## 事实依据\n- 事实',
      },
    }

    expect(getReportExportMarkdown('MEET-1', report)).toBe(report.ai_output.markdown)
    expect(getReportDraftMeta(report)).toEqual({
      draftStatus: '草稿',
      reviewStatus: '待人工复核',
      modelStatus: '规则兜底',
    })
  })

  it('summarizes report reviewer findings for the review officer panel', () => {
    const presentation = buildReportReviewPresentation({
      findings: [
        { type: 'unsupported_claim', severity: 'high', message: '结论缺少案件证据引用' },
        { type: 'tone_conflict', severity: 'medium', message: '报告口径与结论草稿不一致' },
      ],
      suggested_fixes: ['补充现场照片和告警记录引用'],
      manual_review_required: true,
    })

    expect(presentation.totalFindings).toBe(2)
    expect(presentation.severityCounts).toEqual({ high: 1, medium: 1 })
    expect(presentation.findingLines[0]).toContain('unsupported_claim')
    expect(presentation.suggestedFixes).toEqual(['补充现场照片和告警记录引用'])
    expect(presentation.manualReviewRequired).toBe(true)
  })
})
