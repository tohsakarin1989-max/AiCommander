import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import CaseFacilityComparison from './CaseFacilityComparison'
import { expandFacilityRoad, readAutomaticRoadComparison, validateFacilityComparison } from '../../services/roadAnalysis'
import type { CaseFacilityComparison as Content } from '../../services/roadAnalysis'
import api from '../../services/api'

vi.mock('../../services/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
const fixture = (): Content => ({
  schema_version: 'case-facility-comparison-5.2-1', result_id: 'result', content_sha256: 'hash', map_snapshot_id: 'map',
  boundary: '仅供候选比较，不是正式事实',
  calculation: { network_id: 'network', graph_sha256: 'a'.repeat(64), policy_revision: 1, analysis_at: '2026-09-12',
    vehicle: { kind: 'auto', source: 'explicit_reference_assumption' } },
  pool: { input_sha256: 'b'.repeat(64), coverage: { selected: 2, radius_m: 50000, scan_complete: true } },
  result: { algorithm_version: 'facility-roads-5.2.0-1',
    coverage: { recalled: 2, compared: 1, unresolved: 1, complete: false },
    candidates: [{ asset_id: 13, name: '合成设施', rank: 1, score: 30, road_distance_m: 2200,
      rank_change_from_distance: 1, supporting_evidence: ['油品相符'], counter_evidence: ['可达不证明实际来源'],
      information_gaps: ['历史条件不足'], evidence_refs: ['map_asset:13@snapshot:map'] }],
    unresolved: [{ asset_id: 14, state: 'entrance_unknown', score: null }] },
})

describe('道路前置候选的日常展示', () => {
  it('展示真实完成度、版本与反向依据，不把未知当低风险', () => {
    const content = fixture()
    validateFacilityComparison(content)
    const html = renderToStaticMarkup(<CaseFacilityComparison content={content} />)
    expect(html).toContain('召回 2 个设施，完成 1 个比较')
    expect(html).toContain('2.20')
    expect(html).toContain('前移 1 位')
    expect(html).toContain('可达不证明实际来源')
    expect(html).toContain('入口或连接待核')
    expect(html).toContain('不能据此认定全域最优')
    expect(html).toContain('非案件事实')
    expect(html).not.toContain('<button')
  })
  it('自动成果只读查询，绑定原成果与可导出的附件', async () => {
    const content = fixture()
    const artifact = { id: 'artifact', content_sha256: 'c'.repeat(64), content }
    vi.mocked(api.get).mockResolvedValue({ data: { result_id: 'result', content_sha256: 'hash', status: 'completed', artifact } })
    const result = await readAutomaticRoadComparison('result', 'hash', new AbortController().signal)
    expect(result.artifact).toEqual(artifact)
    expect(api.post).not.toHaveBeenCalled()
  })
  it('拒绝统计矛盾、重复编号或缺少反向依据的完成结果', () => {
    for (const change of [
      (v: Content) => { v.result.coverage.compared = 2 },
      (v: Content) => { v.result.coverage.complete = true },
      (v: Content) => { v.result.unresolved[0].asset_id = 13 },
      (v: Content) => { v.result.candidates[0].counter_evidence = [] },
    ]) {
      const value = fixture()
      change(value)
      expect(() => validateFacilityComparison(value)).toThrow('内容不完整')
    }
  })
  it('路径展开仅发送已存成果摘要，拒绝其他父成果的路径', async () => {
    const content = fixture()
    const artifact = { id: 'saved/compare', content_sha256: 'c'.repeat(64) }
    const result = { schema_version: 'case-road-route-4.2.0-1', result_id: content.result_id,
      content_sha256: content.content_sha256, map_snapshot_id: content.map_snapshot_id,
      target: { asset_id: 13, name: '合成设施' }, facility_comparison: artifact,
      artifact: { id: 'saved-route', content_sha256: 'd'.repeat(64) },
      route: { ...content.calculation, shape_polyline6: 'synthetic', distance_m: 2200 } }
    vi.mocked(api.post).mockResolvedValue({ data: result })
    const signal = new AbortController().signal
    await expandFacilityRoad(content, artifact, 13, signal)
    expect(api.post).toHaveBeenLastCalledWith('/road-analysis/artifacts/saved%2Fcompare/facilities/13/routes',
      { content_sha256: artifact.content_sha256 }, { signal })
    vi.mocked(api.post).mockResolvedValue({ data: { ...result, facility_comparison: { ...artifact, id: 'other' } } })
    await expect(expandFacilityRoad(content, artifact, 13, signal)).rejects.toThrow('版本不一致')
    await expect(expandFacilityRoad(content, artifact, 14, signal)).rejects.toThrow('缺少')
  })
})
