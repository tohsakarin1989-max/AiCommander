import type { BatchReviewResult } from '../../types'

export function summarizeBatchReview(result: BatchReviewResult): {
  severity: 'success' | 'warning'
  message: string
  description: string
} {
  const severity = result.failed > 0 ? 'warning' : 'success'
  const issueCount = result.issues.length
  return {
    severity,
    message: `后台处理完成：${result.processed} 起已处理，${result.failed} 起失败，${result.skipped} 起跳过`,
    description: `已形成 ${issueCount} 条待办：低质量案件、结论/报告质量、经验卡复核、奖金指标或材料缺口会进入待办中心。`,
  }
}
