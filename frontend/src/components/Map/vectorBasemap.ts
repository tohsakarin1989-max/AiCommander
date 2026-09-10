import { maplibreGL } from '@maplibre/maplibre-gl-leaflet'
import { setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'
import { offlineMapRequest } from './offlineMapRequest'
import type { ResolvedMapTileConfig } from './mapTiles'
import { vectorZoomLimits } from './vectorZoom'
import { DomUtil } from 'leaflet'
import { guardVectorTransitions } from './vectorLifecycle'

// Vite bundles the worker and its shared module together; no CDN or runtime download.
setWorkerUrl(workerUrl)

export function createVectorBasemap(config: ResolvedMapTileConfig, area?: number) {
  if (!config.snapshotId || !config.styleUrl) throw new Error('invalid_vector_manifest')
  const snapshot = config.snapshotId
  const zooms = vectorZoomLimits(config.options.minNativeZoom, config.options.maxZoom)
  const layer = maplibreGL({
    style: config.styleUrl,
    minZoom: zooms.glMin, maxZoom: zooms.glMax,
    localIdeographFontFamily: false,
    attributionControl: { customAttribution: '© OpenStreetMap contributors · 公共底图，非道路通行证明' },
    transformRequest: url => offlineMapRequest(url, snapshot, window.location.origin, area),
  })
  const stopTransitions = guardVectorTransitions(layer, DomUtil.setTransform)
  // Adapter 0.1.4 assumes GL exists on removal. Leaflet registers the layer before
  // onAdd; a failed WebGL constructor therefore still needs safe DOM cleanup.
  const remove = layer.onRemove
  layer.onRemove = function (map) {
    stopTransitions()
    if (!this.getMaplibreMap()) {
      this.getContainer()?.remove()
      return this
    }
    return remove.call(this, map)
  }
  return layer
}
