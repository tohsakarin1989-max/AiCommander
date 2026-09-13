import type { CaseFacilityComparison } from '../../services/roadAnalysis'
import { validReferencePoint, type ReferencePoint } from '../Map/referencePoint'

/** Only frozen, selected trusted entrances. No guessed centers or straight routes. */
export function facilityComparisonMapModel(content: CaseFacilityComparison) {
  const origin = content.pool.origin
  const referencePoints: ReferencePoint[] = []
  const candidates = content.result.candidates
  const unavailable = { available: false, referencePoints: [], productionAssetIds: [], snapshotRef: content.map_snapshot_id }
  if (!origin || !candidates.length) return unavailable
  referencePoints.push({ id: 'origin', ...origin, title: '案件记录位置', description: '本轮成果冻结位置，非实际轨迹起点认定。' })
  for (const candidate of candidates) {
    const index = candidate.selected_entry_index
    const entries = content.pool.entrances?.[String(candidate.asset_id)]
    if (typeof index !== 'number' || !Number.isSafeInteger(index) || index < 0 || !entries?.[index]) return unavailable
    referencePoints.push({ id: String(candidate.asset_id), ...entries[index],
      title: `${candidate.rank}. ${candidate.name}（可信入口）`,
      description: `参考道路距离 ${(candidate.road_distance_m / 1000).toFixed(2)} 公里。${candidate.counter_evidence[0]}` })
  }
  if (!referencePoints.every(validReferencePoint)) return unavailable
  return { available: true, referencePoints, snapshotRef: content.map_snapshot_id,
    productionAssetIds: candidates.map(candidate => candidate.asset_id) }
}
