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
