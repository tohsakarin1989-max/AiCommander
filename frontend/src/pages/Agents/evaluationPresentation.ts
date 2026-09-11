export function evaluationStatus(value: string): string {
  return ({ pending: '排队中', processing: '运行中', retry: '等待重试', completed: '已完成',
    partial_failure: '部分样本失败', failed: '失败', cancelled: '已取消' } as Record<string, string>)[value] || '状态待确认'
}

export function evaluationMetric(value: number | string | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '未标注或不可计算'
}
