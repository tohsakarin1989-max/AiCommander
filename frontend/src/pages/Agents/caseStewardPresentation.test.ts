import { describe, expect, it } from 'vitest'

import {
  canStartCaseSteward,
  canSubmitCaseStewardRun,
  caseStewardControlReason,
  caseStewardStateLabel,
} from './caseStewardPresentation'

describe('caseStewardPresentation', () => {
  it('仅在指定人员只读试用就绪时允许启动', () => {
    expect(canStartCaseSteward({ enabled: true, can_start: true })).toBe(true)
    expect(canStartCaseSteward({ enabled: true, can_start: false })).toBe(false)
    expect(canStartCaseSteward({ enabled: false, can_start: true })).toBe(false)
  })

  it('必须明确选择案件且不超过后端给出的单次上限', () => {
    const ready = { enabled: true, can_start: true, max_cases_per_run: 30 }
    expect(canSubmitCaseStewardRun(ready, 0)).toBe(false)
    expect(canSubmitCaseStewardRun(ready, 1)).toBe(true)
    expect(canSubmitCaseStewardRun(ready, 31)).toBe(false)
  })

  it('使用面向业务人员的状态名称', () => {
    expect(caseStewardStateLabel('disabled')).toBe('未开放')
    expect(caseStewardStateLabel('unavailable')).toBe('环境未就绪')
    expect(caseStewardStateLabel('ready')).toBe('只读试用中')
  })

  it('一键停用不会把默认开启文案误记为停用原因', () => {
    expect(caseStewardControlReason('启动案件数据管家只读试用', 'enable')).toBe('启动案件数据管家只读试用')
    expect(caseStewardControlReason('启动案件数据管家只读试用', 'disable')).toBe('管理员一键停用案件数据管家试用')
    expect(caseStewardControlReason('竞赛演练结束', 'disable')).toBe('竞赛演练结束')
  })
})
