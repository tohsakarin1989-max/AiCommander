import type L from 'leaflet'
import { CachedTileLayer } from './CachedTileLayer'
import { resolveMapTileConfig, type ResolvedMapTileConfig } from './mapTiles'
import { vectorZoomLimits } from './vectorZoom'

export type BasemapStatus = 'loading' | 'ready' | 'unavailable'
interface MountOptions {
  operationalAreaId?: number
  snapshotRef?: string
  onStatus: (status: BasemapStatus) => void
  onConfig?: (config: ResolvedMapTileConfig) => void
}

/** One lifecycle for all business maps; late async completions cannot touch a removed map. */
export function mountOfflineBasemap(map: L.Map, options: MountOptions): (() => void) & { retry: () => void } {
  let disposed = false
  let layer: L.Layer | undefined
  let unsubscribe = () => {}
  let timer: ReturnType<typeof setTimeout> | undefined
  let generation = 0
  let pinned: ResolvedMapTileConfig | undefined
  let configurationDelivered = false
  const cleanLayer = () => {
    clearTimeout(timer)
    unsubscribe()
    unsubscribe = () => {}
    if (layer && map.hasLayer(layer)) map.removeLayer(layer)
    layer = undefined
  }
  const start = () => {
    if (disposed) return
    const epoch = ++generation
    cleanLayer()
    let failed = false
    const stale = () => disposed || epoch !== generation
    options.onStatus('loading')
    const fail = () => {
      if (stale() || failed) return
      failed = true
      clearTimeout(timer)
      options.onStatus('unavailable')
    }
    const ready = () => {
      if (stale() || failed) return
      clearTimeout(timer)
      options.onStatus('ready')
    }
    timer = setTimeout(fail, 15000)
    const pending = pinned ? Promise.resolve(pinned)
      : resolveMapTileConfig(options.operationalAreaId, options.snapshotRef)
    void pending.then(async config => {
      if (stale() || failed) return
      if (!config.manifestResolved) throw new Error('map_manifest_unavailable')
      pinned = config
      if (config.renderer === 'maplibre') {
        const { createVectorBasemap } = await import('./vectorBasemap')
        if (stale() || failed) return
        const zooms = vectorZoomLimits(config.options.minNativeZoom, config.options.maxZoom)
        map.setMaxZoom(zooms.leafletMax)
        map.setMinZoom(zooms.leafletMin)
        map.setMaxBounds([[-85, -180], [85, 180]])
        const vector = createVectorBasemap(config, options.operationalAreaId)
        layer = vector
        vector.addTo(map)
        const gl = vector.getMaplibreMap()
        gl.on('load', ready)
        gl.on('error', fail)
        unsubscribe = () => { gl.off('load', ready); gl.off('error', fail) }
        if (gl.loaded()) ready()
      } else {
        const raster = new CachedTileLayer(config.url, config.options)
        layer = raster
        raster.on('load', ready)
        raster.on('tileerror', fail)
        unsubscribe = () => { raster.off('load', ready); raster.off('tileerror', fail) }
        raster.addTo(map)
      }
      if (!stale() && !configurationDelivered) {
        options.onConfig?.(config)
        configurationDelivered = true
      }
    }).catch(() => {
      if (stale()) return
      // onAdd may register move/zoom listeners before the GL constructor throws.
      // Detach immediately so panning the failed map cannot call a missing GL map.
      cleanLayer()
      fail()
    })
  }
  start()
  return Object.assign(() => {
    disposed = true
    cleanLayer()
  }, { retry: start })
}
