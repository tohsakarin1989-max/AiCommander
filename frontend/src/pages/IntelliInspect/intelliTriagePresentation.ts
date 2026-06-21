import type { AutomationAlertTriagePack } from '../../services/automationAlerts'

function listBlock(items: string[] | undefined, emptyText: string): string {
  const rows = (items || []).filter(Boolean)
  if (rows.length === 0) return `- ${emptyText}`
  return rows.map(item => `- ${item}`).join('\n')
}

function confidenceText(confidence?: number | null): string {
  if (typeof confidence !== 'number' || !Number.isFinite(confidence)) return '待人工确认'
  return `${Math.round(confidence * 100)}%`
}

export function buildAutomationAlertTriageMarkdown(pack: AutomationAlertTriagePack): string {
  if (pack.ai_output?.markdown) return pack.ai_output.markdown

  const related: string[] = []
  if (pack.alert.related_event_id) related.push(`事件 #${pack.alert.related_event_id}`)
  if (pack.alert.related_case_id) related.push(`案件 #${pack.alert.related_case_id}`)

  const lines = [
    `# 数智告警研判包：${pack.alert.alert_number}`,
    '',
    `- 告警标题：${pack.alert.title}`,
    `- 风险等级：${pack.alert.risk_level}`,
    `- 当前状态：${pack.alert.status}`,
    `- 关联对象：${related.length ? related.join('，') : '暂无关联事件或案件'}`,
    `- 研判结果：${pack.triage_assessment.result || '待人工核查'}`,
    `- 置信度：${confidenceText(pack.triage_assessment.confidence)}`,
    '',
    '## 事实依据',
    listBlock(pack.facts, '暂无事实依据'),
    '',
    '## AI 研判依据',
    listBlock(pack.triage_assessment.basis, '暂无 AI 依据，需人工核查'),
    '',
    '## 信息缺口',
    listBlock(pack.information_gaps, '暂无信息缺口'),
    '',
    '## 建议下一步',
    listBlock(pack.recommended_next_steps, '暂无建议下一步'),
  ]

  if (pack.related_case_context?.facts?.length) {
    lines.push(
      '',
      '## 已关联案件上下文',
      listBlock(pack.related_case_context.facts.slice(0, 8), '暂无案件事实上下文'),
    )
  }

  lines.push(
    '',
    '## 边界说明',
    listBlock(pack.boundary, '仅用于研判辅助，不替代人工核查'),
  )

  return lines.join('\n')
}
