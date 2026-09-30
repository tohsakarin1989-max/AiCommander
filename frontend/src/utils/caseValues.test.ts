import dayjs from 'dayjs'
import { describe, expect, it } from 'vitest'
import { formatCaseTime, formatOilVolume, formatStoredTime, formCaseTime, serializeCaseTime } from './caseValues'

describe('明确保留时间与单位未知', () => {
  it('未知不会成为当前时刻；区间不会冒充精确时间', () => {
    expect(formatCaseTime({ occurred_time: null, time_precision: 'unknown' })).toBe('时间未明确')
    expect(formatStoredTime(null)).toBe('时间未明确')
    expect(formCaseTime(null)).toBeNull()
    expect(formatCaseTime({ time_precision: 'unknown', time_expression: '九月上旬' })).toContain('九月上旬（时间未明确）')
    expect(formatCaseTime({ time_precision: 'interval', occurred_from: '2026-09-01T00:00:00Z', occurred_to: '2026-09-02T00:00:00Z' })).toBe('2026-09-01 08:00 至 2026-09-02 08:00（区间）')
  })
  it('浏览器时区不决定业务记录时区，已存时间编辑往返不漂移', () => {
    const input = dayjs('2026-09-27T12:00:00')
    expect(serializeCaseTime(input, 'Asia/Shanghai')).toBe('2026-09-27T04:00:00.000Z')
    expect(serializeCaseTime(input, 'UTC')).toBe('2026-09-27T12:00:00.000Z')
    expect(serializeCaseTime(formCaseTime('2026-09-27T04:00:00Z'))).toBe('2026-09-27T04:00:00.000Z')
  })
  it('无单位不当成吨，零不当成缺失，不换算不同量纲', () => {
    expect(formatOilVolume(5)).toBe('5 单位未知')
    expect(formatOilVolume(0, 'liter')).toBe('0 升')
    expect(formatOilVolume(5, 'tonne')).toBe('5 吨')
    expect(formatOilVolume(null, 'tonne')).toBe('未记录')
  })
})
