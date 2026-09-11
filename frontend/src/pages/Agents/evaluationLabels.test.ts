import { describe, expect, it } from 'vitest'
import { existingLabel, labelPayload } from './evaluationLabels'
import type { EvaluationLabels } from '../../services/governance'

const data: EvaluationLabels = { dataset_id: 1, name: '合成标签', version: '1', case_ids: [1, 2, 3], cases: [],
  label_assets: [], checksum: 'a', negative_case_ids: [2], ground_truth: {
    '1': [{ hypothesis_type: 'possible_source', expected_asset_ids: [11] }],
  } }
describe('标签编辑', () => {
  it('保留未编辑样本，未标注不作为阴性', () => {
    expect(existingLabel(data, 3).state).toBe('unlabeled')
    expect(labelPayload(data, {})).toEqual({ ground_truth: data.ground_truth, negative_case_ids: [2] })
    const changed = labelPayload(data, { 2: { state: 'unlabeled', labels: [] } })
    expect(changed.ground_truth['1']).toEqual(data.ground_truth['1'])
    expect(changed.negative_case_ids).toEqual([])
    expect(data.negative_case_ids).toEqual([2])
  })
  it('拒绝缺少核验目标的阳性标签', () => {
    expect(() => labelPayload(data, { 3: { state: 'positive', labels: [] } })).toThrow()
    expect(() => labelPayload(data, { 3: { state: 'positive', labels: [{ hypothesis_type: 'activity_area', expected_asset_ids: [] }] } })).toThrow()
    expect(labelPayload(data, { 3: { state: 'positive', labels: [{ hypothesis_type: 'activity_area', expected_asset_ids: [], expected_region_grid: '47:125' }] } }).ground_truth['3']).toHaveLength(1)
  })
})
