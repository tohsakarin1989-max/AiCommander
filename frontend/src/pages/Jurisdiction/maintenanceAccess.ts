/** Viewing / writing cases does not grant permission to maintain map data. */
export function canMaintainArea(
  role: string | undefined,
  scopes: ReadonlyArray<{ operational_area_id: number; access_level: string }>,
  areaId: number | null | undefined,
): boolean {
  if (areaId == null || !['admin', 'analyst'].includes(role ?? '')) return false
  return scopes.some(scope => scope.operational_area_id === areaId && scope.access_level === 'manage')
}
