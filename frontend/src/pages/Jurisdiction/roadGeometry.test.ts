import { describe, expect, it } from 'vitest'
import { roadGeometryCollection } from './roadGeometry'
import type { RoadFeature } from '../../services/internalRoads'

const road = (): RoadFeature => ({ type: 'Feature', id: 'road-1',
  geometry: { type: 'MultiLineString', coordinates: [[[125, 46], [125.01, 46.01]], [[125.02, 46.02], [125.03, 46.03]]] },
  properties: { kind: 'road', name: '<script>来源名称</script>' } })

describe('来源道路显示契约', () => {
  it('保留多段线间的断口，不自动连段或修改输入', () => {
    const input = road()
    const result = roadGeometryCollection([input])
    expect(result.features[0].geometry).toEqual(input.geometry)
    expect(result.features[0].properties?.name).toBe(input.properties.name)
    expect(result.features[0].geometry).not.toBe(input.geometry)
  })
  it('同名道路仍是独立要素，入口保留真实点位', () => {
    const entrance: RoadFeature = { type: 'Feature', id: 'entry', geometry: { type: 'Point', coordinates: [125.005, 46.005] },
      properties: { kind: 'entrance', name: '入口', road_id: 'road-1' } }
    const result = roadGeometryCollection([road(), { ...road(), id: 'road-2' }, entrance])
    expect(result.features.map(item => item.id)).toEqual(['road-1', 'road-2', 'entry'])
    expect(result.features[2].geometry).toEqual(entrance.geometry)
  })
  it.each([[null, 46], [true, 46], ['125', 46], [125, 86], [181, 46], [125, 46, 3]])(
    '拒绝不可显示坐标 %j，不隐式转换或裁剪', (x, y, z?: number) => {
      const item = road()
      item.geometry = { type: 'Point', coordinates: z === undefined ? [x, y] : [x, y, z] }
      expect(() => roadGeometryCollection([item])).toThrow('road_geometry_not_displayable')
    })
})
