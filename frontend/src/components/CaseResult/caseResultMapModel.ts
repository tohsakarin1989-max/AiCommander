import type { CaseMarker } from '../../types'
import type { CaseResult } from '../../types/caseResult'
import { hypothesisMapAssetIds } from '../Map/caseHypothesisMap'

export function caseResultMapModel(result: CaseResult) {
  const { content } = result
  const { latitude, longitude } = content.related_conditions
  const recorded = content.facts_summary.recorded_fields
  const markers: CaseMarker[] = []
  if (typeof latitude === 'number' && Number.isFinite(latitude) && Math.abs(latitude) <= 90
      && typeof longitude === 'number' && Number.isFinite(longitude) && Math.abs(longitude) <= 180) {
    markers.push({ id: content.case_id, lat: latitude, lng: longitude,
      title: typeof recorded.location === 'string' ? recorded.location : '案件记录位置',
      caseNumber: '未随成果冻结',
    })
  }
  return {
    markers, snapshotRef: content.versions.map_snapshot_id ?? undefined,
    productionAssetIds: hypothesisMapAssetIds(content.candidates),
    hypothesisRegions: content.candidates.map(item => ({
      ...item, hypothesis_type: item.category, ruleSupport: item.score,
    })),
  }
}
