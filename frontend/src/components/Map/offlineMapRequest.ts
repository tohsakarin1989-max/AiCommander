import type { RequestParameters } from 'maplibre-gl'
import { offlineFontStackNames } from './offlineVectorStyle'

/** Defense in depth: styles cannot make the browser query other APIs or the public internet. */
export function offlineMapRequest(raw: string, snapshot: string, origin: string, area?: number): RequestParameters {
  const url = new URL(raw, origin)
  const prefix = `/api/maps/${snapshot}/`
  const tail = url.pathname.startsWith(prefix) ? url.pathname.slice(prefix.length) : ''
  const tilePrefix = `/api/maps/tiles/${snapshot}/`
  const tile = url.pathname.startsWith(tilePrefix) ? url.pathname.slice(tilePrefix.length) : ''
  const glyph = /^glyphs\/([^/]+)\/[0-9]+-[0-9]+\.pbf$/.exec(tail)
  let approvedGlyph = false
  if (glyph) {
    try { approvedGlyph = offlineFontStackNames.includes(decodeURIComponent(glyph[1])) }
    catch { throw new Error('offline_resource_forbidden') }
  }
  const permitted = tail === 'style.json'
    || /^sprite(?:@2x)?\.(?:json|png)$/.test(tail)
    || approvedGlyph
    || /^[0-9]+\/[0-9]+\/[0-9]+$/.test(tile)
  if (url.origin !== origin || url.username || url.password || url.hash || !permitted
    || [...url.searchParams.keys()].some(key => key !== 'operational_area_id')
    || url.searchParams.getAll('operational_area_id').length > 1
    || (url.searchParams.has('operational_area_id') && url.searchParams.get('operational_area_id') !== String(area))) {
    throw new Error('offline_resource_forbidden')
  }
  if (area != null) url.searchParams.set('operational_area_id', String(area))
  return { url: url.href, credentials: 'same-origin', cache: 'no-store' }
}
