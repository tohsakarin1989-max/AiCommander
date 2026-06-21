import { describe, expect, it } from 'vitest'
import { summarizeBatchReview } from './batchReviewPresentation'
import type { BatchReviewResult } from '../../types'

describe('batchReviewPresentation', () => {
  it('summarizes successful full background processing without exposing bonus details', () => {
    const summary = summarizeBatchReview({
      job_id: 'job-1',
      status: 'completed',
      progress: 100,
      processed: 188,
      failed: 0,
      skipped: 0,
      issues: [
        { type: 'bonus', priority: 'high', title: '奖金核算指标缺口', detail: '缺少车辆考核类别' },
        { type: 'experience', priority: 'medium', title: '经验卡待复核', detail: '需人工确认' },
      ],
    } as BatchReviewResult)

    expect(summary.severity).toBe('success')
    expect(summary.message).toContain('188 起已处理')
    expect(summary.description).toContain('2 条待办')
    expect(summary.description).not.toContain('¥')
    expect(summary.description).not.toContain('金额')
  })

  it('marks failed items as warning while keeping aggregate wording', () => {
    const summary = summarizeBatchReview({
      job_id: 'job-2',
      status: 'completed',
      progress: 100,
      processed: 10,
      failed: 1,
      skipped: 3,
      issues: [],
    } as BatchReviewResult)

    expect(summary.severity).toBe('warning')
    expect(summary.message).toContain('1 起失败')
    expect(summary.message).toContain('3 起跳过')
  })
})
