import { describe, expect, it } from 'vitest'
import { facilityMatchText, facilityPoint } from './facilitySearchPresentation'
describe('设施匹配线索不是当前事实', () => {
  it('旧名及来源别名明确标注，不替换登记名称', () => {
    const asset = { id: 1, name: '现井名', asset_type: 'well', search_match: { kind: 'historical_name' as const, value: '旧井名' } }
    expect(facilityMatchText(asset)).toBe('历史名称匹配（不是当前名称）：旧井名'); expect(asset.name).toBe('现井名')
    expect(facilityMatchText({ ...asset, search_match: { kind: 'source_alias', value: '来源编号' } })).toContain('不是当前名称')
  })
  it('空值与非法坐标不猜成定位；有效的零坐标保留', () => {
    expect(facilityPoint({ latitude: null, longitude: 125 })).toBeNull()
    expect(facilityPoint({ latitude: 46, longitude: 999 })).toBeNull()
    expect(facilityPoint({ latitude: 0, longitude: 0 })).toEqual([0, 0])
  })
})
