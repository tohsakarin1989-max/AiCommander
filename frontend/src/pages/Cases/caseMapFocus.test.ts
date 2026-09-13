import { describe, expect, it } from 'vitest'
import type { Case } from '../../types'
import { caseFocusCenter, casesWithAuthorizedFocus } from './caseMapFocus'

const record = (id: number, areaId: number, latitude: number | null = 46.5): Case =>
  ({ id, operational_area_id: areaId, latitude, longitude: 125.1 } as Case)

describe('案件地图深链接补查结果', () => {
  it('指定旧案不在当前2000条内仍可加入，更新的补查记录优先且不重复', () => {
    const page = Array.from({ length: 2000 }, (_, index) => record(index + 1, 1))
    const focus = record(9000, 1)
    expect(casesWithAuthorizedFocus(page, focus, 1)).toHaveLength(2001)
    expect(casesWithAuthorizedFocus(page, focus, 1)[0]).toBe(focus)
    expect(casesWithAuthorizedFocus([record(9000, 1)], focus, 1)).toEqual([focus])
  })
  it('切换厂区不会保留前一厂区点，补查不可用时不猜选其他案件', () => {
    expect(casesWithAuthorizedFocus([record(1, 1)], record(2, 2), 2)).toEqual([record(2, 2)])
    expect(casesWithAuthorizedFocus([record(1, 1)], null, 2)).toEqual([])
    expect(casesWithAuthorizedFocus([], record(1, 1), 2)).toEqual([])
    expect(caseFocusCenter(null)).toBeUndefined()
  })
  it('缺少、越界和非有限坐标不会被转换为0或猜测位置', () => {
    for (const latitude of [null, 100, NaN, Infinity]) expect(caseFocusCenter(record(1, 1, latitude))).toBeUndefined()
    expect(caseFocusCenter(record(1, 1))).toEqual([46.5, 125.1])
  })
})
