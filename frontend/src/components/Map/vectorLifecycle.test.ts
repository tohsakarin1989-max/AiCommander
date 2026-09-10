import { describe, expect, it, vi } from 'vitest'
import { guardVectorTransitions } from './vectorLifecycle'

function fixture() {
  const frames: FrameRequestCallback[] = []
  let moved: () => void = () => {}
  const gl = { _actualCanvas: {}, jumpTo: vi.fn(), once: vi.fn((_: string, fn: () => void) => { moved = fn }) }
  const layer = { _map: { getZoom: () => 8, getCenter: () => ({ lat: 46, lng: 124 }),
    getBounds: () => ({ getNorthWest: () => ({}) }), latLngToContainerPoint: () => ({ x: 0, y: 0 }) },
    _glMap: gl, _transitionEnd: () => {}, _resizeContainer: vi.fn(), _zoomEnd: vi.fn() }
  const cancel = vi.fn()
  const stop = guardVectorTransitions(layer, vi.fn(), cb => frames.push(cb), cancel)
  return { layer, frames, stop, cancel, moved: () => moved() }
}

describe('vector transition lifetime', () => {
  it('retains resize and Leaflet-to-GL zoom conversion while mounted', () => {
    const f = fixture()
    f.layer._transitionEnd()
    f.frames[0](0)
    expect(f.layer._resizeContainer).toHaveBeenCalledOnce()
    expect(f.layer._glMap.jumpTo).toHaveBeenCalledWith({ center: { lat: 46, lng: 124 }, zoom: 7 })
    f.moved()
    expect(f.layer._zoomEnd).toHaveBeenCalledOnce()
  })
  it('cancels resize queued before removal, including an already dequeued callback', () => {
    const f = fixture()
    f.layer._transitionEnd()
    f.stop()
    expect(f.cancel).toHaveBeenCalledWith(1)
    f.frames[0](0)
    f.layer._transitionEnd()
    expect(f.frames).toHaveLength(1)
    expect(f.layer._glMap.jumpTo).not.toHaveBeenCalled()
  })
  it('ignores a delayed GL moveend after removal', () => {
    const f = fixture()
    f.layer._transitionEnd()
    f.frames[0](0)
    f.stop()
    f.moved()
    expect(f.layer._zoomEnd).not.toHaveBeenCalled()
  })
})
