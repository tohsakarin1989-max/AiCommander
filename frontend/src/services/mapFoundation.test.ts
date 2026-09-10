import { describe, expect, it } from 'vitest'
import { snapshotLayersToAssets, type MapSnapshotLayers } from './mapFoundation'

describe('snapshotLayersToAssets', () => {
  it('keeps the immutable snapshot identity and display fields', () => {
    const layers: MapSnapshotLayers = {
      type: 'FeatureCollection',
      snapshot_id: 'snapshot-1',
      snapshot_version: 'north-v1',
      truncated: false,
      features: [{
        type: 'Feature',
        id: 71,
        geometry: { type: 'Point', coordinates: [125.1, 46.6] },
        properties: {
          snapshot_feature_id: 71,
          asset_id: 42,
          name: '重点井 42',
          asset_type: 'well',
          source: 'ledger',
          status: 'active',
          verified: true,
          risk_level: 4,
          description: '版本冻结说明',
          tags: ['重点井'],
          attributes: { production_output: 95 },
        },
      }],
    }

    expect(snapshotLayersToAssets(layers)).toEqual([expect.objectContaining({
      id: 42,
      name: '重点井 42',
      latitude: 46.6,
      longitude: 125.1,
      risk_level: 4,
      description: '版本冻结说明',
    })])
  })
})
