import { describe, expect, it, vi } from 'vitest'

import { disposeLeafletHeatMap, guardLeafletHeatLayer } from './leafletLifecycle'

describe('disposeLeafletHeatMap', () => {
  it('ignores a previously queued redraw even when the RAF handle was lost', () => {
    const draw = vi.fn()
    const layer: { _map: object | null; _redraw: () => void } = { _map: {}, _redraw: draw }
    guardLeafletHeatLayer(layer)
    const queued = layer._redraw
    queued()
    expect(draw).toHaveBeenCalledOnce()
    layer._map = null
    queued()
    expect(draw).toHaveBeenCalledOnce()
  })
  it('removes the heat layer before destroying the map', () => {
    const order: string[] = []
    const heatLayer = {}
    const map = {
      hasLayer: vi.fn(() => true),
      removeLayer: vi.fn(() => order.push('remove-layer')),
      stop: vi.fn(() => order.push('stop')),
      remove: vi.fn(() => order.push('remove-map')),
    }

    disposeLeafletHeatMap(map, heatLayer)

    expect(order).toEqual(['remove-layer', 'stop', 'remove-map'])
  })

  it('still destroys the map when the heat layer was already detached', () => {
    const order: string[] = []
    const map = {
      hasLayer: vi.fn(() => false),
      removeLayer: vi.fn(() => order.push('remove-layer')),
      stop: vi.fn(() => order.push('stop')),
      remove: vi.fn(() => order.push('remove-map')),
    }

    disposeLeafletHeatMap(map, null)

    expect(order).toEqual(['stop', 'remove-map'])
  })
})
