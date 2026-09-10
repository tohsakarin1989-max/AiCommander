import { afterEach, describe, expect, it, vi } from 'vitest'
import type L from 'leaflet'
import { mountOfflineBasemap } from './offlineBasemap'
import { resolveMapTileConfig, MAP_TILE_OPTIONS } from './mapTiles'

const mocks = vi.hoisted(() => ({ raster: vi.fn(), vector: vi.fn() }))
vi.mock('./CachedTileLayer', () => ({ CachedTileLayer: mocks.raster }))
vi.mock('./vectorBasemap', () => ({ createVectorBasemap: mocks.vector }))
vi.mock('./mapTiles', async importOriginal => ({
  ...await importOriginal<typeof import('./mapTiles')>(), resolveMapTileConfig: vi.fn(),
}))
const config = { url: '/tiles', manifestResolved: true, options: MAP_TILE_OPTIONS }
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve() }
afterEach(() => { vi.clearAllMocks(); vi.useRealTimers() })

describe('shared basemap lifecycle', () => {
  function fixture() {
    const listeners: Record<string, () => void> = {}
    const layer = { on: vi.fn((key: string, cb: () => void) => { listeners[key] = cb }),
      off: vi.fn(), addTo: vi.fn(), remove: vi.fn() }
    mocks.raster.mockImplementation(function () { return layer })
    const map = { hasLayer: vi.fn(() => true), removeLayer: vi.fn(), setMinZoom: vi.fn(),
      setMaxZoom: vi.fn(), setMaxBounds: vi.fn() } as unknown as L.Map
    const status = vi.fn()
    return { layer, map, status, listeners }
  }
  it('waits for raster load and disposes listeners and layer', async () => {
    const f = fixture()
    vi.mocked(resolveMapTileConfig).mockResolvedValue(config)
    const stop = mountOfflineBasemap(f.map, { onStatus: f.status })
    await flush()
    expect(f.status).toHaveBeenLastCalledWith('loading')
    f.listeners.load()
    expect(f.status).toHaveBeenLastCalledWith('ready')
    stop()
    expect(f.map.removeLayer).toHaveBeenCalledWith(f.layer)
    f.listeners.load()
    expect(f.status).toHaveBeenCalledTimes(2)
  })
  it('never mounts after the owning page unmounts', async () => {
    const f = fixture()
    let resolve!: (value: typeof config) => void
    vi.mocked(resolveMapTileConfig).mockReturnValue(new Promise(done => { resolve = done }))
    const stop = mountOfflineBasemap(f.map, { onStatus: f.status })
    stop(); resolve(config); await flush()
    expect(mocks.raster).not.toHaveBeenCalled()
  })
  it('does not use a fallback whose manifest was not resolved', async () => {
    const f = fixture()
    vi.mocked(resolveMapTileConfig).mockResolvedValue({ ...config, manifestResolved: false })
    mountOfflineBasemap(f.map, { onStatus: f.status }); await flush()
    expect(f.status).toHaveBeenLastCalledWith('unavailable')
    expect(mocks.raster).not.toHaveBeenCalled()
  })
  it('keeps failures unavailable even if a load event follows', async () => {
    const f = fixture()
    vi.mocked(resolveMapTileConfig).mockResolvedValue(config)
    const stop = mountOfflineBasemap(f.map, { onStatus: f.status }); await flush()
    f.listeners.tileerror(); f.listeners.load()
    expect(f.status).toHaveBeenLastCalledWith('unavailable')
    stop()
  })
  it('times out silent loads and prevents later success', async () => {
    vi.useFakeTimers()
    const f = fixture()
    vi.mocked(resolveMapTileConfig).mockResolvedValue(config)
    const stop = mountOfflineBasemap(f.map, { onStatus: f.status }); await flush()
    vi.advanceTimersByTime(15000)
    f.listeners.load()
    expect(f.status).toHaveBeenLastCalledWith('unavailable')
    stop()
  })
  it('retries the pinned configuration without resolving a newly published current', async () => {
    const f = fixture()
    vi.mocked(resolveMapTileConfig).mockResolvedValue(config)
    const stop = mountOfflineBasemap(f.map, { onStatus: f.status }); await flush()
    f.listeners.tileerror()
    stop.retry(); await flush()
    expect(resolveMapTileConfig).toHaveBeenCalledTimes(1)
    expect(mocks.raster).toHaveBeenCalledTimes(2)
    f.listeners.load()
    expect(f.status).toHaveBeenLastCalledWith('ready')
    stop()
  })
  it('delivers configuration after retry recovers a failed vector constructor', async () => {
    const f = fixture()
    const onConfig = vi.fn()
    const gl = { on: vi.fn(), off: vi.fn(), loaded: () => true }
    mocks.vector.mockImplementationOnce(() => { throw new Error('WebGL unavailable') })
      .mockReturnValueOnce({ ...f.layer, getMaplibreMap: () => gl })
    vi.mocked(resolveMapTileConfig).mockResolvedValue({ ...config, renderer: 'maplibre' })
    const stop = mountOfflineBasemap(f.map, { onStatus: f.status, onConfig }); await flush()
    await vi.dynamicImportSettled()
    expect(onConfig).not.toHaveBeenCalled()
    stop.retry(); await flush()
    await vi.dynamicImportSettled()
    expect(onConfig).toHaveBeenCalledOnce()
    stop()
  })
  it('immediately detaches an adapter whose onAdd failed before allowing more interaction', async () => {
    const f = fixture()
    const partial = { ...f.layer, addTo: vi.fn(() => { throw new Error('WebGL creation failed') }) }
    mocks.vector.mockReturnValue(partial)
    vi.mocked(resolveMapTileConfig).mockResolvedValue({ ...config, renderer: 'maplibre' })
    const stop = mountOfflineBasemap(f.map, { onStatus: f.status }); await flush()
    await vi.dynamicImportSettled()
    expect(f.map.removeLayer).toHaveBeenCalledWith(partial)
    expect(f.status).toHaveBeenLastCalledWith('unavailable')
    expect(() => stop()).not.toThrow()
  })
})
