import type { Map as LeafletMap, Point } from 'leaflet'
import type { Map as GLMap } from 'maplibre-gl'

interface Adapter {
  _map?: LeafletMap
  _glMap?: GLMap & { _actualCanvas: HTMLElement }
  _transitionEnd: () => void
  _resizeContainer: () => void
  _zoomEnd: () => void
}

/** Own the deferred transition in pinned adapter 0.1.4, including resize.
 * The upstream callback is not cancellable and dereferences _map after removal.
 */
export function guardVectorTransitions(
  value: unknown,
  setTransform: (element: HTMLElement, offset: Point, scale: number) => void,
  schedule: (callback: FrameRequestCallback) => number = requestAnimationFrame,
  cancel: (id: number) => void = cancelAnimationFrame,
): () => void {
  const layer = value as Adapter
  let disposed = false
  let frame: number | undefined
  layer._transitionEnd = () => {
    if (disposed) return
    if (frame !== undefined) cancel(frame)
    frame = schedule(() => {
      frame = undefined
      const map = layer._map
      const gl = layer._glMap
      if (disposed || !map || !gl) return
      const zoom = map.getZoom()
      const center = map.getCenter()
      const offset = map.latLngToContainerPoint(map.getBounds().getNorthWest())
      layer._resizeContainer()
      setTransform(gl._actualCanvas, offset, 1)
      gl.once('moveend', () => {
        if (!disposed && layer._map === map && layer._glMap === gl) layer._zoomEnd()
      })
      gl.jumpTo({ center, zoom: zoom - 1 })
    })
  }
  return () => {
    disposed = true
    if (frame !== undefined) cancel(frame)
    frame = undefined
  }
}
