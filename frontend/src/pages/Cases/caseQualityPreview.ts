import type { CaseQualityPreview } from '../../types'

export function summarizeCaseQualityPreview(preview: CaseQualityPreview): {
  requiresConfirmation: boolean
  title: string
  description: string
} {
  const missing = preview.missing_required.map(item => item.label).filter(Boolean)
  const warnings = preview.warnings.map(item => item.message).filter(Boolean)
  const requiresConfirmation = preview.level !== 'high' || missing.length > 0 || warnings.length > 0
  const details = [
    missing.length ? `缺项：${missing.slice(0, 4).join('、')}` : '',
    warnings.length ? `提醒：${warnings.slice(0, 2).join('；')}` : '',
  ].filter(Boolean)
  return {
    requiresConfirmation,
    title: `服务端预检评分 ${Math.round(preview.score)} 分`,
    description: details.length
      ? `${details.join('。')}。这些提示不会自动改字段，人工确认后仍可保存。`
      : '关键质量项未发现明显缺口，可继续保存。',
  }
}
