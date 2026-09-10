import type { StyleSpecification, ExpressionSpecification } from 'maplibre-gl'

export const offlineVectorOptions = { minZoom: 6, maxZoom: 19, localIdeographFontFamily: false as const }
const fonts = {
  'cjk-v1': ['Noto Sans CJK SC Regular'],
  'cjk-mongolian-emoji-v1': ['Noto Sans CJK SC Regular', 'Noto Sans Mongolian Regular', 'Noto Emoji Regular'],
} as const
export type OfflineFontProfile = keyof typeof fonts
export const offlineFontStackNames: readonly string[] = Object.freeze(
  Object.values(fonts).map(names => names.join(',')),
)
const label: ExpressionSpecification = ['coalesce', ['get', 'name:zh'], ['get', 'name:latin'], ['get', 'name'], '']

/** Public base geography only. Production and case overlays stay separate. */
export function createOfflineVectorStyle(snapshotId: string, bounds: [number, number, number, number],
  fontProfile: OfflineFontProfile = 'cjk-v1'): StyleSpecification {
  if (typeof fontProfile !== 'string' || !Object.prototype.hasOwnProperty.call(fonts, fontProfile)) {
    throw new Error('离线地图字体配置无效')
  }
  const font = fonts[fontProfile]
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(snapshotId)) {
    throw new Error('离线地图需要已发布的固定版本编号')
  }
  const [west, south, east, north] = bounds
  if (bounds.length !== 4 || !bounds.every(Number.isFinite) || west < -180 || east > 180
    || west >= east || south < -85.051129 || north > 85.051129 || south >= north) {
    throw new Error('离线地图范围无效')
  }
  return {
    version: 8,
    name: '厂区公共地理底图',
    metadata: { 'aic:style-version': 'offline-public-v1', 'aic:snapshot-id': snapshotId,
      'aic:boundary': '道路显示不代表可通行；公开来源缺失不代表现实中不存在' },
    glyphs: `/api/maps/${snapshotId}/glyphs/{fontstack}/{range}.pbf`,
    sources: { public: { type: 'vector', tiles: [`/api/maps/tiles/${snapshotId}/{z}/{x}/{y}`],
      minzoom: 6, maxzoom: 16, bounds: [...bounds],
      attribution: '© OpenStreetMap contributors · Geofabrik · OpenMapTiles schema (CC BY 4.0)' } },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#14212d' } },
      { id: 'landcover', type: 'fill', source: 'public', 'source-layer': 'landcover',
        paint: { 'fill-color': '#203930', 'fill-opacity': 0.55 } },
      { id: 'landuse', type: 'fill', source: 'public', 'source-layer': 'landuse',
        paint: { 'fill-color': '#2b353e', 'fill-opacity': 0.65 } },
      { id: 'parks', type: 'fill', source: 'public', 'source-layer': 'park',
        paint: { 'fill-color': '#2b493a', 'fill-opacity': 0.65 } },
      { id: 'water', type: 'fill', source: 'public', 'source-layer': 'water',
        paint: { 'fill-color': '#204c66' } },
      { id: 'waterways', type: 'line', source: 'public', 'source-layer': 'waterway',
        paint: { 'line-color': '#397c9e', 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.5, 16, 3] } },
      { id: 'buildings', type: 'fill', source: 'public', 'source-layer': 'building', minzoom: 13,
        paint: { 'fill-color': '#465661', 'fill-outline-color': '#6b7b85' } },
      { id: 'boundaries', type: 'line', source: 'public', 'source-layer': 'boundary',
        paint: { 'line-color': '#a5a2bb', 'line-width': 1, 'line-dasharray': [3, 3], 'line-opacity': 0.65 } },
      { id: 'road-casing', type: 'line', source: 'public', 'source-layer': 'transportation',
        filter: ['!=', ['get', 'class'], 'rail'],
        paint: { 'line-color': '#18212b', 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 1, 12, 3, 16, 9] } },
      { id: 'roads', type: 'line', source: 'public', 'source-layer': 'transportation',
        filter: ['!=', ['get', 'class'], 'rail'], layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': ['match', ['get', 'class'], ['motorway', 'trunk'], '#d0b271', ['primary', 'secondary'], '#acb7a8', '#81919b'],
          'line-width': ['interpolate', ['linear'], ['zoom'], 6, 0.5, 12, 1.5, 16, 5] } },
      { id: 'rail', type: 'line', source: 'public', 'source-layer': 'transportation',
        filter: ['==', ['get', 'class'], 'rail'],
        paint: { 'line-color': '#8d9299', 'line-width': 1.4, 'line-dasharray': [2, 2] } },
      { id: 'road-labels', type: 'symbol', source: 'public', 'source-layer': 'transportation_name', minzoom: 12,
        layout: { 'symbol-placement': 'line', 'text-field': structuredClone(label), 'text-font': [...font], 'text-size': 13 },
        paint: { 'text-color': '#d9e0e4', 'text-halo-color': '#14212d', 'text-halo-width': 1.5 } },
      { id: 'poi-labels', type: 'symbol', source: 'public', 'source-layer': 'poi', minzoom: 15,
        layout: { 'text-field': structuredClone(label), 'text-font': [...font], 'text-size': 13, 'text-max-width': 8 },
        paint: { 'text-color': '#b2d4d1', 'text-halo-color': '#14212d', 'text-halo-width': 1.5 } },
      { id: 'place-labels', type: 'symbol', source: 'public', 'source-layer': 'place',
        layout: { 'text-field': structuredClone(label), 'text-font': [...font], 'text-max-width': 10,
          'text-size': ['interpolate', ['linear'], ['zoom'], 6, 14, 12, 18, 16, 21],
          'symbol-sort-key': ['coalesce', ['get', 'rank'], 10] },
        paint: { 'text-color': '#f0f3f5', 'text-halo-color': '#14212d', 'text-halo-width': 2 } },
    ],
  }
}
