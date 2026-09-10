export interface LeafletMapLifecycle<TLayer> {
  hasLayer: (layer: TLayer) => boolean
  removeLayer: (layer: TLayer) => unknown
  stop: () => unknown
  remove: () => unknown
}

/** 先移除热力层以取消其延迟重绘，再销毁地图实例。 */
export function disposeLeafletHeatMap<TLayer>(
  map: LeafletMapLifecycle<TLayer>,
  heatLayer: TLayer | null,
): void {
  try {
    if (heatLayer && map.hasLayer(heatLayer)) {
      map.removeLayer(heatLayer)
    }
  } finally {
    try {
      map.stop()
    } finally {
      map.remove()
    }
  }
}
/** leaflet.heat can clear its RAF id during a synchronous reset while an older
 * callback is still queued. Guard the callback before the layer is mounted. */
export function guardLeafletHeatLayer<TLayer>(layer: TLayer): TLayer {
  const guarded = layer as TLayer & { _redraw?: () => unknown; _map?: unknown }
  const redraw = guarded._redraw
  if (typeof redraw === 'function') {
    guarded._redraw = function () {
      if (guarded._map) return redraw.call(layer)
    }
  }
  return layer
}
