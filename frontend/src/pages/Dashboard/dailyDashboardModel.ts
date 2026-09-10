export function trendHeights(counts: number[]): number[] {
  const maximum = Math.max(0, ...counts)
  return counts.map(count => maximum > 0 ? count / maximum * 100 : 0)
}

export function validMapCoordinate(latitude: number | null, longitude: number | null): boolean {
  return latitude != null && longitude != null && Number.isFinite(latitude) && Number.isFinite(longitude)
    && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180
}

export function shouldFitInitialMap(fitted: boolean, userInteracted: boolean, hasBounds: boolean): boolean {
  return !fitted && !userInteracted && hasBounds
}

export function mayShowCachedDashboard(error: unknown): boolean {
  if (!error || typeof error !== 'object') return true
  const status = 'status' in error ? error.status : undefined
  return status !== 401 && status !== 403 && status !== 404
}
