import { describe, expect, it } from 'vitest'

import { summarizeCaseQualityPreview } from './caseQualityPreview'

describe('caseQualityPreview', () => {
  it('存在缺项时要求人工确认但不阻断保存', () => {
    const result = summarizeCaseQualityPreview({
      score: 52,
      level: 'low',
      category_scores: {},
      missing_required: [
        { field: 'report_unit', label: '报送/责任单位', reason: '业务细则要求完整报送' },
      ],
      warnings: [{ field: 'latitude/longitude', message: '经纬度只填写了一项' }],
      recommendations: [],
      facts: {},
      human_confirmation_required: true,
      boundary: '预检只生成质量提示，不创建或修改案件。',
    })

    expect(result.requiresConfirmation).toBe(true)
    expect(result.title).toContain('52')
    expect(result.description).toContain('报送/责任单位')
    expect(result.description).toContain('仍可保存')
  })

  it('高质量且无问题时可直接保存', () => {
    const result = summarizeCaseQualityPreview({
      score: 92,
      level: 'high',
      category_scores: {},
      missing_required: [],
      warnings: [],
      recommendations: [],
      facts: {},
      human_confirmation_required: true,
      boundary: '预检只生成质量提示，不创建或修改案件。',
    })

    expect(result.requiresConfirmation).toBe(false)
  })
})
