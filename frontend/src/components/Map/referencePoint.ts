export interface ReferencePoint {
  id: string
  latitude: number
  longitude: number
  title: string
  description: string
}

export function validReferencePoint(point: ReferencePoint): boolean {
  return typeof point.id === 'string' && !!point.id && typeof point.title === 'string'
    && typeof point.description === 'string' && typeof point.latitude === 'number'
    && Number.isFinite(point.latitude) && Math.abs(point.latitude) <= 85
    && typeof point.longitude === 'number' && Number.isFinite(point.longitude) && Math.abs(point.longitude) <= 180
}
