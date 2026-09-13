import type { Case } from '../../types'

/** The focused case comes from an independently authorized GET, never a guessed point. */
export function casesWithAuthorizedFocus(rows: Case[], focus: Case | null, areaId: number | null): Case[] {
  const visible = rows.filter(row => row.operational_area_id === areaId)
  if (!focus || focus.operational_area_id !== areaId) return visible
  return [focus, ...visible.filter(row => row.id !== focus.id)]
}

export function caseFocusCenter(focus: Case | null): [number, number] | undefined {
  if (!focus || typeof focus.latitude !== 'number' || typeof focus.longitude !== 'number'
      || !Number.isFinite(focus.latitude) || !Number.isFinite(focus.longitude)
      || Math.abs(focus.latitude) > 90 || Math.abs(focus.longitude) > 180) return undefined
  return [focus.latitude, focus.longitude]
}
