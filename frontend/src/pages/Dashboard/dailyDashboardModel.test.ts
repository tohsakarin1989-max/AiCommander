import { describe, expect, it } from 'vitest'
import { trendHeights, validMapCoordinate, shouldFitInitialMap, mayShowCachedDashboard } from './dailyDashboardModel'

describe('daily dashboard presentation', () => {
  it('keeps the viewport through network failures but hides revoked access', () => {
    expect(mayShowCachedDashboard({ status: 503 })).toBe(true)
    expect(mayShowCachedDashboard(new Error('network'))).toBe(true)
    for (const status of [401, 403, 404]) expect(mayShowCachedDashboard({ status })).toBe(false)
  })
  it('does not draw zero observations as a positive bar', () => {
    expect(trendHeights([0, 5, 10])).toEqual([0, 50, 100])
    expect(trendHeights([0, 0])).toEqual([0, 0])
  })
  it('accepts northern Qiqihar instead of clipping to the old oilfield rectangle', () => {
    expect(validMapCoordinate(48.9, 125)).toBe(true)
    expect(validMapCoordinate(null, 125)).toBe(false)
    expect(validMapCoordinate(91, 125)).toBe(false)
  })
  it('fits once on data arrival, never after a user interaction or refresh', () => {
    expect(shouldFitInitialMap(false, false, true)).toBe(true)
    expect(shouldFitInitialMap(true, false, true)).toBe(false)
    expect(shouldFitInitialMap(false, true, true)).toBe(false)
    expect(shouldFitInitialMap(false, false, false)).toBe(false)
  })
})
