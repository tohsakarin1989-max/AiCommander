import { describe, expect, it, vi } from 'vitest'
const mocks = vi.hoisted(() => ({ create: vi.fn(), worker: vi.fn() }))
vi.mock('@maplibre/maplibre-gl-leaflet', () => ({ maplibreGL: mocks.create }))
vi.mock('maplibre-gl', () => ({ setWorkerUrl: mocks.worker }))
vi.mock('leaflet', () => ({ DomUtil: { setTransform: vi.fn() } }))
vi.mock('./vectorLifecycle', () => ({ guardVectorTransitions: () => vi.fn() }))
vi.mock('maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url', () => ({ default: '/assets/worker.js' }))
import { createVectorBasemap } from './vectorBasemap'
import { MAP_TILE_OPTIONS } from './mapTiles'
describe('vector adapter failure cleanup', () => {
  it('removes a partially initialized container without calling the broken adapter remover', () => {
    const remove = vi.fn()
    const normalRemove = vi.fn(() => { throw new Error('missing GL') })
    const partial = { getMaplibreMap: () => undefined, getContainer: () => ({ remove }), onRemove: normalRemove }
    mocks.create.mockReturnValue(partial)
    const layer = createVectorBasemap({ url: '', snapshotId: 'fixture', styleUrl: '/style',
      manifestResolved: true, options: MAP_TILE_OPTIONS })
    expect(() => layer.onRemove({} as never)).not.toThrow()
    expect(remove).toHaveBeenCalledOnce()
    expect(normalRemove).not.toHaveBeenCalled()
  })
  it('uses the original cleanup for a successfully initialized map', () => {
    const normalRemove = vi.fn()
    mocks.create.mockReturnValue({ getMaplibreMap: () => ({}), onRemove: normalRemove })
    const layer = createVectorBasemap({ url: '', snapshotId: 'fixture', styleUrl: '/style',
      manifestResolved: true, options: MAP_TILE_OPTIONS })
    layer.onRemove({} as never)
    expect(normalRemove).toHaveBeenCalledOnce()
  })
})
