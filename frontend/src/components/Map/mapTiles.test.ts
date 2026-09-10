import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  MAP_TILE_OPTIONS,
  MAP_TILE_URL,
  isImmutableOfflineTileUrl,
  resolveMapTileConfig,
} from './mapTiles'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('offline map tile presentation', () => {
  const snapshot = '11111111-1111-4111-8111-111111111111'
  const vectorManifest = () => ({
    schema_version: '2.0', renderer: 'maplibre', snapshot_id: snapshot,
    tile_url: `/api/maps/tiles/${snapshot}/{z}/{x}/{y}`,
    style_url: `/api/maps/${snapshot}/style.json`,
    min_zoom: 6, max_zoom: 16, display_max_zoom: 19,
    bounds: [124, 46, 126, 48],
  })

  it('selects vector rendering with local version-bound resources, without raster blanks', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => vectorManifest() }))
    const config = await resolveMapTileConfig(7)
    expect(config.renderer).toBe('maplibre')
    expect(config.styleUrl).toBe(`/api/maps/${snapshot}/style.json?operational_area_id=7`)
    expect(config.url).not.toContain('blank_missing')
    expect(config.options.maxNativeZoom).toBe(16)
    expect(config.options.maxZoom).toBe(19)
  })

  it.each([
    { style_url: 'https://example.com/style.json' },
    { style_url: '/api/maps/current/style.json' },
    { tile_url: '/api/maps/tiles/current/{z}/{x}/{y}' },
    { renderer: 'raster' }, { bounds: [124, 46, 126, 91] },
    { max_zoom: 19 }, { snapshot_id: 'current' },
  ])('fails closed for malformed vector manifests: %j', async (override) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true,
      json: async () => ({ ...vectorManifest(), ...override }) }))
    await expect(resolveMapTileConfig(7)).rejects.toThrow('invalid_vector_manifest')
  })

  it('rejects a vector response that does not match the requested historical version', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => vectorManifest() }))
    await expect(resolveMapTileConfig(7, '22222222-2222-4222-8222-222222222222'))
      .rejects.toThrow('invalid_vector_manifest')
  })
  it('keeps map interaction inside the packaged native zoom range', () => {
    expect(MAP_TILE_URL).toContain('blank_missing=true')
    expect(MAP_TILE_OPTIONS.minNativeZoom).toBe(6)
    expect(MAP_TILE_OPTIONS.maxNativeZoom).toBe(14)
    expect(MAP_TILE_OPTIONS.maxZoom).toBe(19)
  })

  it('only persists tiles whose URL pins an immutable snapshot', () => {
    expect(isImmutableOfflineTileUrl('/api/maps/tiles/current/14/123/456')).toBe(false)
    expect(isImmutableOfflineTileUrl('/api/maps/tiles/snapshot-v2/14/123/456')).toBe(true)
    expect(isImmutableOfflineTileUrl('https://tiles.example/14/123/456')).toBe(false)
  })

  it('pins the current published snapshot and reads its zoom and attribution', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        snapshot_id: 'snapshot-v2',
        tile_url: '/api/maps/tiles/snapshot-v2/{z}/{x}/{y}',
        production_layer_url: '/api/maps/snapshot-v2/layers',
        min_zoom: 8,
        max_zoom: 16,
        attribution: '批准的公共地图来源',
        bounds: [124, 46, 126, 48],
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const config = await resolveMapTileConfig(7)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/maps/current/manifest?operational_area_id=7',
      { cache: 'no-store', credentials: 'same-origin' },
    )
    expect(config.url).toBe(
      '/api/maps/tiles/snapshot-v2/{z}/{x}/{y}?blank_missing=true&operational_area_id=7',
    )
    expect(config.productionLayerUrl).toBe(
      '/api/maps/snapshot-v2/layers?operational_area_id=7',
    )
    expect(config.options.minNativeZoom).toBe(8)
    expect(config.options.maxNativeZoom).toBe(16)
    expect(config.options.attribution).toBe('批准的公共地图来源')
    expect(config.bounds).toEqual([[46, 124], [48, 126]])
    expect(config.manifestResolved).toBe(true)
  })

  it('resolves the exact production-layer snapshot instead of mixing with current', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        snapshot_id: 'snapshot-a',
        tile_url: '/api/maps/tiles/snapshot-a/{z}/{x}/{y}',
        min_zoom: 6,
        max_zoom: 14,
        attribution: '受控来源',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const config = await resolveMapTileConfig(7, 'snapshot-a')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/maps/snapshot-a/manifest?operational_area_id=7',
      { cache: 'no-store', credentials: 'same-origin' },
    )
    expect(config.url).toContain('/api/maps/tiles/snapshot-a/')
    expect(config.url).not.toContain('/current/')
  })

  it('never drifts a pinned layer back to current when its manifest is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))

    const config = await resolveMapTileConfig(7, 'snapshot-a')

    expect(config.url).toBe(
      '/api/maps/tiles/snapshot-a/{z}/{x}/{y}?blank_missing=true&operational_area_id=7',
    )
    expect(config.manifestResolved).toBe(false)
  })
})
