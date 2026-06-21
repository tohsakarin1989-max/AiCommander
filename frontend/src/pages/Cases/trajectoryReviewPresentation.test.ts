import { describe, expect, it } from 'vitest'
import { summarizeTrajectoryReview } from './trajectoryReviewPresentation'
import type { TrajectoryReview } from '../../types'

describe('trajectoryReviewPresentation', () => {
  it('summarizes route-condition review without prediction wording', () => {
    const summary = summarizeTrajectoryReview({
      case_ids: [1, 2],
      method: 'path_condition_review',
      facts: [{ case_id: 1 }, { case_id: 2 }],
      path_conditions: [{ type: 'segment' }],
      inferences: [{ level: 'low' }],
      information_gaps: ['缺少道路结构化数据'],
      reusable_suggestions: ['先核事实再确认推断'],
      boundary: '仅复盘已发生案件路径条件，不做犯罪预测，不输出未来地点。',
    } as TrajectoryReview)

    expect(summary.title).toBe('路径条件复盘')
    expect(summary.factCount).toBe(2)
    expect(summary.conditionCount).toBe(1)
    expect(summary.boundary).toContain('不做犯罪预测')
    expect(JSON.stringify(summary)).not.toContain('下一个可能位置')
  })

  it('marks legacy predict response as deprecated review entry', () => {
    const summary = summarizeTrajectoryReview({
      case_ids: [1],
      method: 'path_condition_review',
      facts: [],
      path_conditions: [],
      inferences: [],
      information_gaps: ['轨迹点不足'],
      reusable_suggestions: [],
      boundary: '仅复盘已发生案件路径条件，不做犯罪预测，不输出未来地点。',
      deprecated: true,
    } as TrajectoryReview)

    expect(summary.deprecated).toBe(true)
    expect(summary.gapCount).toBe(1)
  })
})
