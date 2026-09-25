import { describe, expect, it } from 'vitest'
import { parseRegionalContext, regionalCalendarDate, regionalContextPath, writeRegionalContext } from './regionalContext'

describe('区域选择与条件接续', () => {
  it('日期控件按北京时间展示UTC共享窗口，不改动原时刻', () => {
    expect(regionalCalendarDate('2026-09-24T16:00:00Z')).toBe('2026-09-25')
    expect(regionalCalendarDate('2026-09-25T00:00:00+08:00')).toBe('2026-09-25')
    expect(regionalCalendarDate('bad')).toBe('')
  })
  it('同辖区跨视图保留时间与稳定实体编号，不传播冻结报告身份', () => {
    const source = new URLSearchParams('operational_area_id=2&assetId=5&eventId=8&caseId=11&start_date=2026-09-01T00:00:00Z&end_date=2026-10-01T00:00:00Z&resultId=history&revision=9&facility_source_snapshot=old')
    const next = new URLSearchParams(regionalContextPath('/area-analysis', source).split('?')[1])
    expect(parseRegionalContext(next)).toMatchObject({ areaId: 2, assetId: 5, eventId: 8, caseId: 11, startDate: '2026-09-01T00:00:00Z', endDate: '2026-10-01T00:00:00Z' })
    expect(next.has('resultId')).toBe(false)
    expect(next.has('revision')).toBe(false)
    expect(next.has('facility_source_snapshot')).toBe(false)
  })
  it('主动切换辖区清除旧辖区选中对象，保留时间窗', () => {
    const next = writeRegionalContext(new URLSearchParams('operational_area_id=1&assetId=2&caseId=3&eventId=4&start_date=2026-09-01'), { operational_area_id: 9 })
    expect(next.toString()).toBe('start_date=2026-09-01&operational_area_id=9')
  })
  it.each(['assetId=0', 'assetId=1bad', 'eventId=-1', 'assetId=2&assetId=3', 'operational_area_id=2&operational_area_id=3', 'start_date=bad', 'start_date=2026-10-01&end_date=2026-09-01'])('拒绝非法条件而不扩大范围：%s', query => {
    expect(parseRegionalContext(new URLSearchParams(query)).error).toBeTruthy()
  })
  it('时间窗调整不丢稳定选择，目标对象覆盖来源对象', () => {
    const next = writeRegionalContext(new URLSearchParams('assetId=8&eventId=9'), { end_date: '2026-10-01T00:00:00+08:00' })
    expect(parseRegionalContext(next).assetId).toBe(8)
    expect(regionalContextPath('/events?eventId=3', next)).toContain('eventId=3')
  })
})
