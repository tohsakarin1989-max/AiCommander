import { describe, expect, it } from 'vitest'
import dayjs from 'dayjs'
import { entryDifferenceFields, resolveEntryDifferences, restoreEntryValues, serializeEntryValues } from './caseDraftSnapshot'

describe('私有草稿与冲突快照', () => {
  it('未完成字段和嵌套数量保留，业务时区日期可往返', () => {
    const values = { time_timezone: 'Asia/Shanghai', time_precision: 'interval', occurred_from: dayjs('2026-10-01T08:30:00'), occurred_to: null,
      initial_measurements: [{ value: 0, unit: 'unknown', measured_at: dayjs('2026-10-01T09:00:00') }], description: '合成敏感输入', source_detail: '' }
    const stored = serializeEntryValues(values)
    expect(stored.occurred_from).toBe('2026-10-01T00:30:00.000Z')
    expect(stored.occurred_to).toBeNull()
    const restored = restoreEntryValues(stored)
    expect(dayjs.isDayjs(restored.occurred_from)).toBe(true)
    expect(serializeEntryValues(restored)).toEqual(stored)
  })
  it('不保存派生结果和正式记录身份，不丢明细稳定编号', () => {
    expect(serializeEntryValues({ id: 10, features: { cached: 'derived' }, initial_persons: [{ id: 4, name: '合成' }] }))
      .toEqual({ initial_persons: [{ id: 4, name: '合成' }] })
  })
  it('只有逐项确认后才可生成合并结果，重复明细不按位置合并', () => {
    const mine = { location: '甲', description: '同文', initial_persons: [{ id: 1, name: '同名' }, { id: 2, name: '同名' }] }
    const latest = { location: '乙', description: '同文', initial_persons: [{ id: 2, name: '同名' }, { id: 1, name: '同名' }] }
    expect(entryDifferenceFields(mine, latest)).toEqual(['location', 'initial_persons'])
    expect(() => resolveEntryDifferences(mine, latest, { location: 'mine' })).toThrow('逐项确认')
    expect(resolveEntryDifferences(mine, latest, { location: 'mine', initial_persons: 'latest' })).toEqual({ ...latest, location: '甲' })
  })
})
