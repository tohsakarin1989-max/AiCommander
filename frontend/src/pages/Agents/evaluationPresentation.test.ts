import { describe, expect, it } from 'vitest'
import { evaluationMetric, evaluationStatus, evaluationPolicies, evaluationPolicyLabel } from './evaluationPresentation'

describe('固定评测口径', () => {
  it('不将缺标签和非数值显示为零准确率', () => {
    for (const value of [null, undefined, NaN, Infinity, 'unknown']) expect(evaluationMetric(value)).toBe('未标注或不可计算')
    expect(evaluationMetric(0)).toBe('0.0%')
    expect(evaluationMetric(0.7)).toBe('70.0%')
  })
  it('明确显示部分失败与未识别状态', () => {
    expect(evaluationStatus('partial_failure')).toBe('部分样本失败')
    expect(evaluationStatus('pending')).toBe('排队中')
    expect(evaluationStatus('incomplete')).toBe('输入或计算未完成')
    expect(evaluationStatus('unexpected')).toBe('状态待确认')
  })
  it('设施对照只提供原来源与道路规则，不混淆路由重放', () => {
    expect(evaluationPolicies('facility_source').map(item => item.value)).toEqual(['captured', 'facility_captured', 'facility_candidate'])
    expect(evaluationPolicies().map(item => item.value)).toEqual(['captured', 'current_candidate'])
    expect(evaluationPolicyLabel('facility_captured')).toBe('冻结道路评分规则')
    expect(evaluationPolicyLabel('unknown')).toBe('版本未记录')
  })
})
