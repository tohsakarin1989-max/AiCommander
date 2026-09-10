export interface CircleHypothesisRegion {
  latitude: number
  longitude: number
  radiusM: number
}

export function parseCircleHypothesisRegion(
  region: Record<string, unknown> | null | undefined,
): CircleHypothesisRegion | null {
  if (!region || region.type !== 'circle' || !Array.isArray(region.center)) return null
  if (region.center.length !== 2) return null
  const longitude = Number(region.center[0])
  const latitude = Number(region.center[1])
  const radiusM = Number(region.radius_m)
  if (
    !Number.isFinite(latitude)
    || !Number.isFinite(longitude)
    || !Number.isFinite(radiusM)
    || latitude < -90
    || latitude > 90
    || longitude < -180
    || longitude > 180
    || radiusM <= 0
    || radiusM > 20_000
  ) return null
  return { latitude, longitude, radiusM }
}

export function hypothesisRegionColor(hypothesisType: string): string {
  if (hypothesisType === 'possible_source') return '#ef4444'
  if (hypothesisType === 'storage_area') return '#f59e0b'
  if (hypothesisType === 'activity_area') return '#a78bfa'
  if (hypothesisType === 'transfer_route') return '#38bdf8'
  return '#94a3b8'
}

export function hypothesisMapAssetIds(
  hypotheses: Array<{ evidence_refs: string[] }>,
): number[] {
  const ids = new Set<number>()
  hypotheses.forEach(item => {
    item.evidence_refs.forEach(reference => {
      const match = reference.match(/^map_asset:(\d+)@snapshot:/)
      if (!match) return
      const id = Number(match[1])
      if (Number.isSafeInteger(id) && id > 0) ids.add(id)
    })
  })
  return [...ids].sort((left, right) => left - right).slice(0, 50)
}
