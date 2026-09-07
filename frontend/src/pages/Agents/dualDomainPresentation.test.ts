import { describe, expect, it } from 'vitest'

import {
  canStartDualDomain,
  canSubmitDualDomainRun,
  dualDomainControlHint,
  dualDomainControlReason,
  dualDomainStateLabel,
} from './dualDomainPresentation'

describe('dualDomainPresentation', () => {
  it('仅在指定人员只读试用就绪时允许启动', () => {
    expect(canStartDualDomain({ enabled: true, can_start: true })).toBe(true)
    expect(canStartDualDomain({ enabled: true, can_start: false })).toBe(false)
    expect(canStartDualDomain({ enabled: false, can_start: true })).toBe(false)
  })

  it('案件和地图资源都必须显式选择且不得超过上限', () => {
    const ready = {
      enabled: true,
      can_start: true,
      max_cases_per_run: 10,
      max_assets_per_run: 100,
    }
    expect(canSubmitDualDomainRun(ready, 0, 1)).toBe(false)
    expect(canSubmitDualDomainRun(ready, 1, 0)).toBe(false)
    expect(canSubmitDualDomainRun(ready, 1, 1)).toBe(true)
    expect(canSubmitDualDomainRun(ready, 11, 1)).toBe(false)
    expect(canSubmitDualDomainRun(ready, 1, 101)).toBe(false)
  })

  it('向业务人员明确只读和历史复盘边界', () => {
    expect(dualDomainStateLabel('disabled')).toBe('未开放')
    expect(dualDomainStateLabel('unavailable')).toBe('环境未就绪')
    expect(dualDomainStateLabel('ready')).toBe('只读研判中')
    expect(dualDomainControlHint({ enabled: true, can_start: true, state: 'ready' }))
      .toContain('历史时空条件')
  })

  it('一键停用使用独立的审计原因', () => {
    expect(dualDomainControlReason('启动双域融合只读试用', 'enable'))
      .toBe('启动双域融合只读试用')
    expect(dualDomainControlReason('启动双域融合只读试用', 'disable'))
      .toBe('管理员一键停用双域融合研判试用')
    expect(dualDomainControlReason('竞赛演练结束', 'disable')).toBe('竞赛演练结束')
  })
})
