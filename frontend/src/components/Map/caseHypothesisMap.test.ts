import { describe, expect, it } from 'vitest'

import {
  hypothesisMapAssetIds,
  hypothesisRegionColor,
  parseCircleHypothesisRegion,
} from './caseHypothesisMap'

describe('case hypothesis map helpers', () => {
  it('parses a bounded circle region emitted by the deterministic analysis', () => {
    expect(parseCircleHypothesisRegion({
      type: 'circle',
      center: [125.1, 46.6],
      radius_m: 800,
      precision: 'area_only',
    })).toEqual({ latitude: 46.6, longitude: 125.1, radiusM: 800 })
  })

  it('rejects malformed or over-broad regions', () => {
    expect(parseCircleHypothesisRegion({ type: 'circle', center: [125.1], radius_m: 800 })).toBeNull()
    expect(parseCircleHypothesisRegion({ type: 'circle', center: [125.1, 46.6], radius_m: 50_000 })).toBeNull()
  })

  it('uses distinct colors for the four business hypothesis types', () => {
    expect(new Set([
      hypothesisRegionColor('possible_source'),
      hypothesisRegionColor('storage_area'),
      hypothesisRegionColor('activity_area'),
      hypothesisRegionColor('transfer_route'),
    ]).size).toBe(4)
  })

  it('extracts only bounded map evidence ids for the frozen production layer', () => {
    expect(hypothesisMapAssetIds([
      { evidence_refs: ['case_profile:p1', 'map_asset:42@snapshot:s1'] },
      { evidence_refs: ['map_asset:7@snapshot:s1', 'map_asset:42@snapshot:s1'] },
      { evidence_refs: ['case:9', 'map_asset:not-a-number@snapshot:s1'] },
    ])).toEqual([7, 42])
  })
})
