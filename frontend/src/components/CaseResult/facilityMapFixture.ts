import type { CaseFacilityComparison } from '../../services/roadAnalysis'

/** Synthetic UI fixture. Never used as application fallback data. */
export const facilityMapFixture = (): CaseFacilityComparison => ({
  schema_version: 'case-facility-comparison-5.2-1', result_id: 'ui-fixture', content_sha256: 'synthetic', map_snapshot_id: 'synthetic-map',
  boundary: '合成界面样本，不是实际业务成果。',
  calculation: { network_id: 'synthetic-network', graph_sha256: 'a'.repeat(64), policy_revision: 1,
    analysis_at: '2026-09-12T00:00:00Z', vehicle: { kind: 'auto', source: 'explicit_reference_assumption' } },
  pool: { input_sha256: 'b'.repeat(64), coverage: { selected: 2, radius_m: 50000, scan_complete: true },
    origin: { latitude: 46.6, longitude: 125.1 },
    entrances: { '13': [{ latitude: 46.62, longitude: 125.14 }, { latitude: 46.61, longitude: 125.12 }],
      '14': [{ latitude: 46.58, longitude: 125.08 }] } },
  result: { algorithm_version: 'facility-roads-5.2.0-1', coverage: { recalled: 2, compared: 2, unresolved: 0, complete: true },
    candidates: [13, 14].map((id, index) => ({ asset_id: id, name: `合成井场${index + 1}`, rank: index + 1,
      selected_entry_index: index === 0 ? 1 : 0, score: 50 - index, road_distance_m: 2200 + index * 1000,
      rank_change_from_distance: index === 0 ? 1 : -1, supporting_evidence: ['合成油品与设施条件相符'],
      counter_evidence: ['道路可达不证明实际来源'], information_gaps: ['现场情况仍待核验'],
      evidence_refs: [`map_asset:${id}@snapshot:synthetic-map`] })), unresolved: [] },
})
