import { describe, expect, it } from 'vitest'
import { evaluationMetric, evaluationStatus } from './evaluationPresentation'

describe('固定评测口径', () => {
  it('不将缺标签和非数值显示为零准确率', () => {
    for (const value of [null, undefined, NaN, Infinity, 'unknown']) expect(evaluationMetric(value)).toBe('未标注或不可计算')
    expect(evaluationMetric(0)).toBe('0.0%')
    expect(evaluationMetric(0.7)).toBe('70.0%')
  })
  it('明确显示部分失败与未识别状态', () => {
    expect(evaluationStatus('partial_failure')).toBe('部分样本失败')
    expect(evaluationStatus('pending')).toBe('排队中')
    expect(evaluationStatus('unexpected')).toBe('状态待确认')
  })
})
