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
    referencePoints: content.composition ? content.road_map?.reference_points.map(point => ({
      id: point.id, latitude: point.latitude, longitude: point.longitude, title: point.title,
      description: '本组合冻结可信入口，不代表实际行驶轨迹或正式关联。',
    })) : undefined,
    productionAssetIds: content.composition ? content.road_map?.production_asset_ids ?? [] : hypothesisMapAssetIds(content.candidates),
    hypothesisRegions: content.composition ? [] : content.candidates.map(item => ({
      ...item, hypothesis_type: item.category, ruleSupport: item.score,
    })),
  }
}
