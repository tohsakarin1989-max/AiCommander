import type { FixedScorerPolicy } from '../../services/governance'

export function evaluationStatus(value: string): string {
  return ({ pending: '排队中', processing: '运行中', retry: '等待重试', completed: '已完成',
    incomplete: '输入或计算未完成', partial_failure: '部分样本失败', failed: '失败', cancelled: '已取消' } as Record<string, string>)[value] || '状态待确认'
}

export function evaluationPolicyLabel(policy?: string): string {
  return ({ captured: '冻结原空间规则', current_candidate: '当前原空间规则',
    facility_captured: '冻结道路评分规则', facility_candidate: '当前道路评分规则' } as Record<string, string>)[policy || ''] || '版本未记录'
}

export function evaluationPolicies(family?: string): Array<{ value: FixedScorerPolicy; label: string }> {
  const policies: FixedScorerPolicy[] = family === 'facility_source'
    ? ['captured', 'facility_captured', 'facility_candidate'] : ['captured', 'current_candidate']
  return policies.map(value => ({ value, label: evaluationPolicyLabel(value) }))
}

export function evaluationMetric(value: number | string | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '未标注或不可计算'
}
