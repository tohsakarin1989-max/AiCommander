import { describe, expect, it } from 'vitest'

import { summarizeCaseQualityPreview } from './caseQualityPreview'

describe('caseQualityPreview', () => {
  it('v6.1 缺项不再强制二次确认，最多三项提示；只有格式错误阻止保存', () => {
    const data = { score: 0, level: 'low' as const, category_scores: {}, missing_required: [], warnings: [], recommendations: [], facts: {}, human_confirmation_required: false, boundary: '',
      validation: { status: 'valid' as const, can_save: true, errors: [], warnings: [] },
      priority_gaps: ['时间', '地点', '油品', '第四项'].map(label => ({ field: label, label, reason: '未知可保存', category: 'context', affected_capabilities: [] })),
    }
    const result = summarizeCaseQualityPreview(data)
    expect(result.requiresConfirmation).toBe(false); expect(result.canSave).toBe(true)
    expect(result.description).toContain('未知内容可以保存'); expect(result.description).not.toContain('第四项')
    const invalid = summarizeCaseQualityPreview({ ...data, validation: { status: 'invalid', can_save: false, errors: [{ field: 'oil_volume', label: '数量', message: '数量不能为负' }], warnings: [] } })
    expect(invalid.canSave).toBe(false); expect(invalid.description).toContain('数量不能为负')
  })
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
    expect(result.title).not.toContain('52')
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
