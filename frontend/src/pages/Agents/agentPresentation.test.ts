import { describe, expect, it } from 'vitest'

import {
  agentErrorMessage,
  agentExecutionModeLabel,
  agentEventLabel,
  agentResultText,
  agentStatusLabel,
  canReviewAgentRun,
  evidenceCoverage,
} from './agentPresentation'

describe('agent presentation', () => {
  it('uses explicit labels for durable runtime states', () => {
    expect(agentStatusLabel('waiting_approval')).toBe('等待人工复核')
    expect(agentStatusLabel('degraded')).toBe('降级完成')
    expect(agentStatusLabel('expired')).toBe('审批已过期')
  })

  it('distinguishes the primary local rules engine from model fallback', () => {
    expect(agentExecutionModeLabel('deterministic')).toBe('内网规则引擎')
    expect(agentExecutionModeLabel('agent_lab')).toBe('脱敏模型辅助')
    expect(agentExecutionModeLabel('deterministic_fallback')).toBe('模型降级，内网规则接管')
  })

  it('only lets admins review candidate mutations', () => {
    expect(canReviewAgentRun('admin')).toBe(true)
    expect(canReviewAgentRun('analyst')).toBe(false)
    expect(canReviewAgentRun('viewer')).toBe(false)
  })

  it('calculates evidence coverage without claiming evidence for empty conclusions', () => {
    expect(evidenceCoverage(4, 4)).toBe(100)
    expect(evidenceCoverage(2, 4)).toBe(50)
    expect(evidenceCoverage(0, 0)).toBe(0)
  })

  it('never passes an error response object into the UI message layer', () => {
    expect(agentErrorMessage(new Error('队列暂不可用'), '启动失败')).toBe('队列暂不可用')
    expect(agentErrorMessage({ detail: { detail: '内部对象' } }, '启动失败')).toBe('启动失败')
    expect(agentErrorMessage({ detail: '源数据版本已变化' }, '重放失败')).toBe('源数据版本已变化')
  })

  it('presents structured evidence and trace events in business language', () => {
    expect(agentEventLabel('verification_started')).toBe('开始验证证据')
    expect(agentResultText({
      case_id: 8,
      quality_score: 72,
      quality_level: 'medium',
      missing_count: 2,
      warning_count: 1,
    })).toContain('案件证据 #8｜质量分 72')
    expect(agentResultText({
      case_id: 8,
      risk_score: 25,
      historical_frequency: { case_count: 3, days: 365, radius_km: 1.5 },
      modus_tags: ['夜间活动'],
    })).toContain('365天/1.5公里内历史记录 3 条')
  })
})
