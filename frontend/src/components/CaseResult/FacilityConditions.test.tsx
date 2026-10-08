import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import FacilityConditions from './FacilityConditions'
import { validFacilityConditions, validRankingChanges, type FacilityConditionComparison, type FacilityRankingChanges } from '../../services/facilityConditions'

const fixture = (): FacilityConditionComparison => ({ schema_version: 'facility-conditions-6.3-1', boundary: '条件支持不确认来源',
  rows: [{ asset_id: 1, name: '合成设施', eligibility: 'unresolved', rank: null, score: null,
    conditions: [{ key: 'entrance', label: '可信入口', state: 'unknown', reason: '入口资料未知', dependencies: ['入口核验记录'], evidence_refs: [] }],
    source_context: { valid_at: null, known_at: '2026-09-27', version_id: null, state: 'unknown' }, boundary: '不是现实不可达' }],
  priority_gaps: [{ key: 'entrance', label: '入口资料', reason: '影响道路比较', asset_ids: [1], condition_keys: ['entrance'], dependencies: ['入口核验记录'] }] })

describe('设施全池对照', () => {
  it('关键补充列出真实受影响设施、阻断数和依据，不承诺收益', () => {
    const input = fixture()
    input.priority_gaps[0].key = 'road'
    input.rows[0].conditions[0].key = 'road'
    input.rows[0].conditions[0].evidence_refs = ['map_asset:1@test']
    Object.assign(input.priority_gaps[0], { ranking_version: 'facility-gap-impact-7.5-1',
      priority_basis: { blocked_candidates: 1, unresolved_candidates: 1, ranked_candidates: 0, affected_candidates: 1 },
      impacts: [{ asset_id: 1, name: '合成设施', eligibility: 'unresolved', blocks_comparison: true,
        reason: input.rows[0].conditions[0].reason, evidence_refs: ['map_asset:1@test'] }] })
    expect(validFacilityConditions(input, 1)).toBe(true)
    const html = renderToStaticMarkup(<FacilityConditions comparison={input} />)
    for (const text of ['1 个道路比较受阻', '不是预估收益', '合成设施（#1）', 'map_asset:1@test']) expect(html).toContain(text)
    input.priority_gaps[0].priority_basis!.affected_candidates = 100
    expect(validFacilityConditions(input, 1)).toBe(false)
    input.priority_gaps[0].priority_basis!.affected_candidates = 1
    input.priority_gaps[0].impacts![0].asset_id = 900
    expect(validFacilityConditions(input, 1)).toBe(false)
  })
  it('未排名对象仍展示未知、依赖与无前版，不伪造排名变化', () => {
    const input = fixture()
    const changes: FacilityRankingChanges = { state: 'no_baseline', baseline: null, changes: [], context_changes: [], boundary: '不做单因果归因' }
    expect(validFacilityConditions(input, 1)).toBe(true)
    expect(validRankingChanges(changes)).toBe(true)
    const html = renderToStaticMarkup(<FacilityConditions comparison={input} changes={changes} />)
    for (const value of ['资料未知', '入口核验记录', '不是新增待办', '没有前版可比', '不是现实不可达']) expect(html).toContain(value)
  })
  it('缺失召回行或伪造风险类型均被拒绝', () => {
    const input = fixture()
    expect(validFacilityConditions(input, 2)).toBe(false)
    input.rows[0].conditions[0].state = 'low_risk' as never
    expect(validFacilityConditions(input, 1)).toBe(false)
  })
})
