import { describe, expect, it } from 'vitest'

import {
  canSubmitMapStewardRun,
  canStartMapSteward,
  mapStewardControlReason,
  mapStewardControlHint,
  mapStewardStateLabel,
} from './mapStewardPresentation'

describe('map steward pilot presentation', () => {
  it('uses plain business labels for every pilot state', () => {
    expect(mapStewardStateLabel('disabled')).toBe('试用未开启')
    expect(mapStewardStateLabel('suspended')).toBe('候选写入已暂停')
    expect(mapStewardStateLabel('read_only')).toBe('只读检查')
    expect(mapStewardStateLabel('ready')).toBe('受控辅助运行中')
  })

  it('starts only for an explicitly authorized pilot user', () => {
    expect(canStartMapSteward({ enabled: true, can_start: true })).toBe(true)
    expect(canStartMapSteward({ enabled: true, can_start: false })).toBe(false)
    expect(canStartMapSteward({ enabled: false, can_start: true })).toBe(false)
  })

  it('requires an explicit non-empty map asset scope before submission', () => {
    const ready = { enabled: true, can_start: true }
    expect(canSubmitMapStewardRun(ready, 0)).toBe(false)
    expect(canSubmitMapStewardRun(ready, 1)).toBe(true)
    expect(canSubmitMapStewardRun({ enabled: true, can_start: false }, 1)).toBe(false)
    expect(mapStewardControlReason('启动地图数据管家受控试用', 'pause')).toBe('管理员暂停候选写入')
    expect(mapStewardControlReason('夜间故障演练', 'disable')).toBe('夜间故障演练')
  })

  it('explains suspended and unauthorized states without configuration jargon', () => {
    expect(mapStewardControlHint({
      state: 'suspended',
      can_start: true,
      can_apply_changes: false,
    })).toContain('仍可检查数据')
    expect(mapStewardControlHint({
      state: 'ready',
      can_start: false,
      can_apply_changes: false,
    })).toContain('未被加入试用名单')
  })
})
