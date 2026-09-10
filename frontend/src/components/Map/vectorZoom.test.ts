import { describe, expect, it } from 'vitest'
import { vectorZoomLimits } from './vectorZoom'

describe('vector camera zoom conversion', () => {
  it('never lets a short map fit below native tiles', () => {
    const limits = vectorZoomLimits(6, 19)
    expect(limits.leafletMin - 1).toBe(6)
    expect(limits.glMin).toBe(6)
    expect(limits.leafletMax - 1).toBe(19)
    expect(limits.glMax).toBe(19)
  })
  it('supports a single native level without creating an inverted camera range', () => {
    const limits = vectorZoomLimits(16, 16)
    expect(limits.leafletMin).toBe(limits.leafletMax)
  })
})
