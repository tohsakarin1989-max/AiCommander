import { describe, expect, it, vi } from 'vitest'

import { disposeLeafletHeatMap } from './leafletLifecycle'

describe('disposeLeafletHeatMap', () => {
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
