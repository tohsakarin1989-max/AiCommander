import { describe, expect, it } from 'vitest'
import { businessMapValid } from './businessAnswerMapModel'
const map = { schema_version: 'business-answer-map-8.4-1', state: 'ready', boundary: '冻结点位不是轨迹',
  information_gaps: [], snapshots: [{ id: 'snapshot-1', version: 'map-v2', area_id: 1 }],
  coverage: { shown: 1, point_limit: 100, truncated: false }, points: [{ kind: 'case', object_id: 1, label: '合成记录',
    role: 'discovery', latitude: 46, longitude: 125, map_snapshot_id: 'snapshot-1', evidence_refs: ['case:1'] }] }
describe('回答地图冻结合同', () => {
  it('使用固定版本与明确角色，不接受动态current', () => {
    expect(businessMapValid(map)).toBe(true)
    expect(businessMapValid({ ...map, snapshots: [{ id: 'current', version: 'map-v2', area_id: 1 }] })).toBe(false)
  })
  it('点位、计数和来源版本不一致时不混入当前坐标', () => {
    expect(businessMapValid({ ...map, points: [{ ...map.points[0], latitude: 91 }] })).toBe(false)
    expect(businessMapValid({ ...map, points: [{ ...map.points[0], map_snapshot_id: 'other' }] })).toBe(false)
    expect(businessMapValid({ ...map, coverage: { ...map.coverage, shown: 2 } })).toBe(false)
  })
})
