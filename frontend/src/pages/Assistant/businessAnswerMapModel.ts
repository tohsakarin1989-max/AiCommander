import type { BusinessAnswerMapContext } from '../../services/intelligentQueries'

export function businessMapValid(value: unknown): value is BusinessAnswerMapContext {
  if (!value || typeof value !== 'object') return false
  const map = value as BusinessAnswerMapContext
  return map.schema_version === 'business-answer-map-8.4-1'
    && ['ready', 'partial', 'unavailable'].includes(map.state) && typeof map.boundary === 'string'
    && Array.isArray(map.information_gaps) && map.information_gaps.every(gap => typeof gap === 'string')
    && Array.isArray(map.snapshots) && map.snapshots.every(row => row && typeof row.id === 'string'
      && /^[a-zA-Z0-9_-]{1,100}$/.test(row.id) && row.id !== 'current'
      && Number.isSafeInteger(row.area_id) && row.area_id > 0 && typeof row.version === 'string' && !!row.version)
    && new Set(map.snapshots.map(row => row.id)).size === map.snapshots.length
    && Array.isArray(map.points) && map.points.length <= 100 && map.points.every(row => row
      && ['case', 'asset'].includes(row.kind) && Number.isSafeInteger(row.object_id) && row.object_id > 0
      && typeof row.label === 'string' && ['discovery', 'incident', 'facility'].includes(row.role)
      && typeof row.latitude === 'number' && Number.isFinite(row.latitude) && Math.abs(row.latitude) <= 85
      && typeof row.longitude === 'number' && Number.isFinite(row.longitude) && Math.abs(row.longitude) <= 180
      && map.snapshots.some(snapshot => snapshot.id === row.map_snapshot_id)
      && Array.isArray(row.evidence_refs) && row.evidence_refs.every(ref => typeof ref === 'string'))
    && !!map.coverage && map.coverage.shown === map.points.length && typeof map.coverage.truncated === 'boolean'
}

export const pointRoles: Record<string, string> = { discovery: '发现／查获地点', incident: '明确案发地点', facility: '登记设施快照' }
