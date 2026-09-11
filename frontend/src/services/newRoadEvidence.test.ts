import { describe, expect, it } from 'vitest'
import { buildNewRoadEvidence } from './newRoadEvidence'
import type { RoadFeature } from './internalRoads'

const feature: RoadFeature = { type: 'Feature', id: 'r1', properties: { name: '合成路', kind: 'road' },
  geometry: { type: 'LineString', coordinates: [[125, 46], [125, 46.001]] } }
const row = { segment: 1, endpoint: 'start' as const, node: '12345678901' }

describe('新增道路连接录入', () => {
  it('界面分段从1转换为0，保留大节点编号和源版本', () => {
    expect(buildNewRoadEvidence(feature, 'a'.repeat(64), [row])).toEqual({ kind: 'new_road',
      public_source_sha256: 'a'.repeat(64), connections: [{ component: 0, endpoint: 'start', osm_node_id: 12345678901 }] })
  })
  it('不猜测未填写分段、不接受重复端点或失真编号', () => {
    expect(() => buildNewRoadEvidence(feature, 'a'.repeat(64), [])).toThrow('每个独立分段')
    expect(() => buildNewRoadEvidence(feature, 'a'.repeat(64), [row, row])).toThrow('只能记录一次')
    expect(() => buildNewRoadEvidence(feature, 'a'.repeat(64), [{ ...row, node: '9007199254740993' }])).toThrow('有效')
  })
})
