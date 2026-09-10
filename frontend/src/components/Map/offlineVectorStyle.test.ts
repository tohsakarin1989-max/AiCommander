import { describe, expect, it } from 'vitest'
import { validateStyleMin } from '@maplibre/maplibre-gl-style-spec'
import { createOfflineVectorStyle, offlineVectorOptions } from './offlineVectorStyle'

const snapshot = '5e364292-1976-4ade-b6cc-123456789abc'
const bounds: [number, number, number, number] = [122, 45, 127, 50]

describe('offline vector style', () => {
  it('uses the registered composite font profile without changing the legacy default', () => {
    const style = createOfflineVectorStyle(snapshot, bounds, 'cjk-mongolian-emoji-v1')
    expect(validateStyleMin(style)).toEqual([])
    for (const layer of style.layers) {
      if (layer.type === 'symbol') expect(layer.layout?.['text-font']).toEqual([
        'Noto Sans CJK SC Regular', 'Noto Sans Mongolian Regular', 'Noto Emoji Regular',
      ])
    }
    for (const layer of createOfflineVectorStyle(snapshot, bounds).layers) {
      if (layer.type === 'symbol') expect(layer.layout?.['text-font']).toEqual(['Noto Sans CJK SC Regular'])
    }
  })
  it.each(['unknown', '__proto__', null, []].map(profile => ({ profile })))('rejects an unknown font profile $profile', ({ profile }) => {
    // @ts-expect-error Exercise untrusted runtime input, not just TypeScript callers.
    expect(() => createOfflineVectorStyle(snapshot, bounds, profile)).toThrow()
  })
  it('passes the installed MapLibre style specification validator', () => {
    expect(validateStyleMin(createOfflineVectorStyle(snapshot, bounds))).toEqual([])
  })
  it('binds all external resources to one immutable local snapshot', () => {
    const style = createOfflineVectorStyle(snapshot, bounds)
    expect(style.sources.public).toMatchObject({ type: 'vector', minzoom: 6, maxzoom: 16,
      tiles: [`/api/maps/tiles/${snapshot}/{z}/{x}/{y}`] })
    expect(style.glyphs).toBe(`/api/maps/${snapshot}/glyphs/{fontstack}/{range}.pbf`)
    expect(style.sprite).toBeUndefined()
    expect(offlineVectorOptions.localIdeographFontFamily).toBe(false)
    expect(offlineVectorOptions.maxZoom).toBe(19)
  })
  it('preserves complete basic geography and places labels above roads', () => {
    const layers = createOfflineVectorStyle(snapshot, bounds).layers
    const sources = layers.flatMap(layer => 'source-layer' in layer ? [layer['source-layer']] : [])
    expect(sources).toEqual(expect.arrayContaining(['transportation', 'water', 'waterway', 'building', 'boundary', 'place', 'poi']))
    expect(layers.findIndex(layer => layer.id === 'place-labels')).toBeGreaterThan(layers.findIndex(layer => layer.id === 'roads'))
    expect(new Set(layers.map(layer => layer.id)).size).toBe(layers.length)
  })
  it.each(['current', '../other', '//example.com', 'https://example.com', snapshot + '?x=1'])('rejects non-immutable identity %s', id => {
    expect(() => createOfflineVectorStyle(id, bounds)).toThrow()
  })
  it.each([[127,45,122,50], [122,NaN,127,50], [122,-90,127,50], [122,45,Infinity,50]])('rejects invalid bounds %s', (...value) => {
    expect(() => createOfflineVectorStyle(snapshot, value as typeof bounds)).toThrow()
  })
  it('does not mutate input or share returned style objects', () => {
    const first = createOfflineVectorStyle(snapshot, bounds)
    first.layers.pop()
    expect(createOfflineVectorStyle(snapshot, bounds).layers.length).toBeGreaterThan(first.layers.length)
    expect(bounds).toEqual([122,45,127,50])
  })
})
