import { describe, expect, it } from 'vitest'
import { caseLocationDraft, locationCoordinateError } from './caseLocationDraft'
import { buildCaseEntrySubmitPayload } from './caseEntrySubmitPayload'

describe('地点角色坐标不猜测', () => {
  it('已知点正确回填经纬度；区域原几何无编辑时保留', () => {
    const point = caseLocationDraft({ role: 'incident', precision: 'exact', geometry: { type: 'Point', coordinates: [124, 47] } })
    expect(point).toMatchObject({ ui_longitude: 124, ui_latitude: 47 })
    const geometry = { type: 'Polygon', coordinates: [[[124, 47], [125, 47], [124, 48], [124, 47]]] }
    const payload = buildCaseEntrySubmitPayload({ initial_locations: [{ role: 'mentioned', precision: 'area', geometry }] }, { mode: 'edit' })
    expect(payload.initial_locations?.[0].geometry).toEqual(geometry)
  })
  it('不完整、越界及精确无点均报错；未知地点允许保存', () => {
    expect(locationCoordinateError({ precision: 'unknown' })).toBeNull()
    expect(locationCoordinateError({ ui_latitude: 45 })).toContain('同时')
    expect(locationCoordinateError({ precision: 'exact' })).toContain('精确位置')
    expect(locationCoordinateError({ ui_latitude: 91, ui_longitude: 124 })).toContain('纬度')
    expect(locationCoordinateError({ precision: 'exact', ui_latitude: 47, ui_longitude: 124 })).toBeNull()
  })
})
