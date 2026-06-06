import { describe, expect, it } from 'vitest'
import type { AutomationAlertTriagePack } from '../../services/automationAlerts'
import { buildAutomationAlertTriageMarkdown } from './intelliTriagePresentation'

const pack: AutomationAlertTriagePack = {
  alert: {
    id: 7,
    alert_number: 'AUTO-2026-0007',
    title: '井口压力异常',
    status: 'pending',
    risk_level: 'high',
    related_event_id: 12,
    related_case_id: 188,
  },
  facts: ['告警来源：A2 参数异常', '位置：新站作业区 3 号井'],
  triage_assessment: {
    result: '建议人工现场核查',
    confidence: 0.76,
    basis: ['压力骤降', '夜间时段'],
  },
  information_gaps: ['缺少云台截图', '缺少雷达目标复核'],
  recommended_next_steps: ['核对井口设备状态', '调阅同时间段视频'],
  related_event: {
    id: 12,
    event_number: 'EVT-12',
    handling_result: '待核查',
  },
  related_case_context: {
    scope: { mode: 'single_case', days: 90, limit: 10, radius_km: 2 },
    system_boundary: ['只做研判辅助'],
    facts: ['案件编号：AI2026-00032'],
    pattern_inferences: [],
    inferences: [],
    prevention_references: [],
    recommendations: [],
    information_gaps: [],
    evidence_index: [],
    evidence_refs: [],
    boundary: ['只做研判辅助'],
    recommended_questions: [],
    llm_prompt: '',
    markdown: '',
    generated_at: '2026-06-03T00:00:00Z',
  },
  boundary: ['不替代人工核查', '不自动派发处置任务'],
  ai_output: {
    title: '标准化告警研判包',
    output_type: 'automation_alert_triage_pack',
    draft_status: 'draft',
    review_status: 'pending_review',
    model_status: 'deterministic_fallback',
    generated_at: '2026-06-06T00:00:00Z',
    facts: ['标准事实'],
    inferences: [{ claim: '标准推断', basis: ['标准依据'], confidence: 'medium' }],
    recommendations: [{ title: '标准建议', action: '人工复核参数曲线', basis: ['标准依据'], evidence: [], priority: 'medium' }],
    information_gaps: ['标准缺口'],
    evidence_refs: [{ id: 'alert:AUTO-2026-0007', kind: 'automation_alert', summary: '标准证据', basis: [] }],
    boundary: ['不得把告警建议写成已执行任务'],
    markdown: '# 标准化告警研判包\n\n## 事实依据\n- 标准事实',
  },
}

describe('intelliTriagePresentation', () => {
  it('builds a copyable markdown review note from a triage pack', () => {
    const legacyPack = { ...pack, ai_output: undefined }
    const markdown = buildAutomationAlertTriageMarkdown(legacyPack)

    expect(markdown).toContain('# 数智告警研判包：AUTO-2026-0007')
    expect(markdown).toContain('## 事实依据')
    expect(markdown).toContain('- 告警来源：A2 参数异常')
    expect(markdown).toContain('## AI 研判依据')
    expect(markdown).toContain('- 压力骤降')
    expect(markdown).toContain('## 信息缺口')
    expect(markdown).toContain('- 缺少云台截图')
    expect(markdown).toContain('## 已关联案件上下文')
    expect(markdown).toContain('- 案件编号：AI2026-00032')
    expect(markdown).toContain('不自动派发处置任务')
  })

  it('prefers backend normalized ai_output markdown when available', () => {
    const markdown = buildAutomationAlertTriageMarkdown(pack)

    expect(markdown).toBe(pack.ai_output?.markdown)
    expect(markdown).toContain('标准化告警研判包')
  })
})
