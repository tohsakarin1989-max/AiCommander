import { describe, expect, it } from 'vitest'
import { dashboardWindow, rollingWindowParams } from './dashboardWindow'
import { regionalContextPath } from '../../services/regionalContext'

describe('大屏滚动与固定时间窗', () => {
  it('默认滚动7天，URL镜像日期不会被当成请求截止时间', () => {
    expect(dashboardWindow(new URLSearchParams()).request).toBeUndefined()
    const first = rollingWindowParams(new URLSearchParams('operational_area_id=2'), 7, { start: '2026-09-18T00:00:00Z', end: '2026-09-25T00:00:00Z' })
    const next = rollingWindowParams(first, 7, { start: '2026-09-18T00:00:30Z', end: '2026-09-25T00:00:30Z' })
    expect(dashboardWindow(first)).toEqual(dashboardWindow(next))
    expect(dashboardWindow(next).rolling).toBe(true)
    expect(next.get('end_date')).toBe('2026-09-25T00:00:30Z')
  })
  it('跨页继承本次窗口，显式共享起止不变成滚动', () => {
    const source = rollingWindowParams(new URLSearchParams('operational_area_id=2'), 30, { start: '2026-08-25T00:00:00Z', end: '2026-09-25T00:00:00Z' })
    const target = new URLSearchParams(regionalContextPath('/area-analysis', source).split('?')[1])
    expect(target.has('dashboard_period')).toBe(false)
    expect(dashboardWindow(target).rolling).toBe(false)
    expect(dashboardWindow(target).request?.end_date).toBe('2026-09-25T00:00:00Z')
  })
  it('区域全部历史进入大屏不能静默缩成7天', () => {
    const params = new URLSearchParams(regionalContextPath('/dashboard', new URLSearchParams('operational_area_id=2&time_scope=all_history')).split('?')[1])
    expect(dashboardWindow(params)).toMatchObject({ allHistory: true, rolling: false })
  })
  it('普通菜单进入大屏无显式全历史选择时继续滚动7天', () => {
    const params = new URLSearchParams(regionalContextPath('/dashboard', new URLSearchParams('operational_area_id=2')).split('?')[1])
    expect(dashboardWindow(params)).toMatchObject({ allHistory: false, rolling: true, days: 7 })
  })
})
