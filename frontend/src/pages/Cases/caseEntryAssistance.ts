import type { JurisdictionAsset } from '../../services/jurisdiction'
import type { CaseStructurePreview } from '../../types'

export function intakeEvidenceLabel(preview: CaseStructurePreview, field: string): string {
  const anchor = preview.evidence_anchors?.find(item => item.field === field)
  if (!anchor?.text?.trim() || anchor.reference_status !== 'verified') return '未定位到原文依据，请核对'
  return `原文依据：${anchor.text}`
}

export function intakeCapabilityLabel(status?: string): string {
  if (status === 'llm_success') return '已连接模型提取，仍需核对原文'
  if (status === 'llm_failed') return '模型本次未完成，已使用本地规则'
  if (status === 'deterministic_fallback') return '本地规则提取，不代表模型已启用'
  return '候选字段，提取方式未确认'
}

export function facilityHasUsablePoint(asset: JurisdictionAsset): boolean {
  return asset.verified === true && (!asset.geometry_type || asset.geometry_type.toLowerCase() === 'point')
    && typeof asset.latitude === 'number' && Number.isFinite(asset.latitude) && Math.abs(asset.latitude) <= 90
    && typeof asset.longitude === 'number' && Number.isFinite(asset.longitude) && Math.abs(asset.longitude) <= 180
}

/** Selecting a directory entry does not establish an incident association. */
export function facilityEntryPatch(asset: JurisdictionAsset, includePoint = false): Record<string, unknown> {
  const location = asset.address ? `${asset.name}（${asset.address}）` : asset.name
  return { location, ...(includePoint && facilityHasUsablePoint(asset)
    ? { latitude: asset.latitude, longitude: asset.longitude } : {}) }
}
