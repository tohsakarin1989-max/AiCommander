import { beforeEach, expect, it, vi } from 'vitest'
import api from './api'
import { caseReachableRoads, type CaseRoadComparison } from './roadAnalysis'

vi.mock('./api', () => ({ default: { post: vi.fn() } }))
beforeEach(() => vi.resetAllMocks())
const comparison: CaseRoadComparison = {
  schema_version: 'case-road-comparison-4.2.0-1', result_id: 'result', content_sha256: 'hash',
  map_snapshot_id: 'snapshot', targets: [], information_gaps: [], boundary: '参考',
  matrix: { network_id: 'network', graph_sha256: 'graph', policy_revision: 1, analysis_at: 'time', cells: [] },
}
const fixture = () => ({ schema_version: 'case-reachable-roads-4.2.0-1', result_id: 'result',
  content_sha256: 'hash', map_snapshot_id: 'snapshot', metric: 'distance', budget: 3000,
  boundary: '仅道路参考', information_gaps: [], reachability: { network_id: 'network', graph_sha256: 'graph',
    analysis_at: 'time', native_completion_contract: 'completed-v1', roads: { type: 'FeatureCollection', features: [
      { type: 'Feature', geometry: { type: 'LineString', coordinates: [[125, 46], [125.1, 46.1]] } },
      { type: 'Feature', geometry: { type: 'LineString', coordinates: [[126, 47], [126.1, 47.1]] } },
    ] } } })
it('只发送预算和版本，不发送点位车型；保留分支而不跨空隙连线', async () => {
  vi.mocked(api.post).mockResolvedValue({ data: fixture() })
  const signal = new AbortController().signal
  const result = await caseReachableRoads(comparison, { metric: 'distance', distance_m: 3000 }, signal)
  expect(result.segments).toEqual([[[46, 125], [46.1, 125.1]], [[47, 126], [47.1, 126.1]]])
  expect(api.post).toHaveBeenCalledWith('/road-analysis/case-results/result/reachable-roads', {
    metric: 'distance', distance_m: 3000, content_sha256: 'hash', network_id: 'network',
    graph_sha256: 'graph', analysis_at: 'time',
  }, { signal })
})
it.each(['version', 'budget', 'marker', 'geometry'])('拒绝错误成果：%s', async fault => {
  const data = fixture()
  if (fault === 'version') data.reachability.graph_sha256 = 'other'
  if (fault === 'budget') data.budget = 5000
  if (fault === 'marker') data.reachability.native_completion_contract = 'unknown'
  if (fault === 'geometry') data.reachability.roads.features[0].geometry.coordinates[0] = [Infinity, 46]
  vi.mocked(api.post).mockResolvedValue({ data })
  await expect(caseReachableRoads(comparison, { metric: 'distance', distance_m: 3000 }, new AbortController().signal)).rejects.toThrow()
})
it('信息缺口不绘制伪造道路', async () => {
  vi.mocked(api.post).mockResolvedValue({ data: { ...fixture(), reachability: null, information_gaps: ['缺坐标'] } })
  expect((await caseReachableRoads(comparison, { metric: 'distance', distance_m: 3000 }, new AbortController().signal)).segments).toEqual([])
})
