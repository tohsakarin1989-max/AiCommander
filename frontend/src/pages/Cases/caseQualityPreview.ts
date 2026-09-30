import type { CaseQualityPreview } from '../../types'

export function summarizeCaseQualityPreview(preview: CaseQualityPreview): {
  requiresConfirmation: boolean
  canSave: boolean
  title: string
  description: string
} {
  if (preview.validation) {
    const errors = preview.validation.errors.map(item => item.message)
    const gaps = (preview.priority_gaps || []).slice(0, 3).map(item => `${item.label}：${item.reason}`)
    return {
      requiresConfirmation: false,
      canSave: preview.validation.can_save,
      title: preview.validation.can_save ? '资料预检完成' : '请修正字段格式',
      description: errors.length ? errors.join('；') : gaps.length ? `${gaps.join('；')}。未知内容可以保存，以上为按需补充。` : '已知资料可以保存；资料齐备不代表案件办结。',
    }
  }
  const missing = preview.missing_required.map(item => item.label).filter(Boolean)
  const warnings = preview.warnings.map(item => item.message).filter(Boolean)
  const requiresConfirmation = preview.level !== 'high' || missing.length > 0 || warnings.length > 0
  const details = [
    missing.length ? `缺项：${missing.slice(0, 4).join('、')}` : '',
    warnings.length ? `提醒：${warnings.slice(0, 2).join('；')}` : '',
  ].filter(Boolean)
  return {
    requiresConfirmation,
    canSave: true,
    title: '已有资料提示',
    description: details.length
      ? `${details.join('。')}。这些提示不会自动改字段，人工确认后仍可保存。`
      : '关键质量项未发现明显缺口，可继续保存。',
  }
}
