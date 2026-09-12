import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { facilityComparisonMapModel } from './facilityComparisonMapModel'
import { facilityMapFixture } from './facilityMapFixture'
import { LegacyCandidateReference } from './CaseRoadComparison'

describe('同版本道路候选地图', () => {
  it('沿用选中的第二入口及最终排名，不选最近点或绘制虚构路线', () => {
    const content = facilityMapFixture()
    const model = facilityComparisonMapModel(content)
    expect(model.available).toBe(true)
    expect(model.productionAssetIds).toEqual([13, 14])
    expect(model.referencePoints[1]).toMatchObject({ id: '13', latitude: 46.61, longitude: 125.12 })
    expect(model.referencePoints[1].title).toContain('1. 合成井场1')
    expect(model.referencePoints[0].title).toBe('案件记录位置')
    expect(model.snapshotRef).toBe('synthetic-map')
    expect(model).not.toHaveProperty('referencePath')
    expect(model).not.toHaveProperty('hypothesisRegions')
  })
  it('缺失、非法或错配端点不回退到零坐标与其他入口', () => {
    for (const change of [
      (v: ReturnType<typeof facilityMapFixture>) => { delete v.pool.origin },
      (v: ReturnType<typeof facilityMapFixture>) => { v.pool.origin!.latitude = NaN },
      (v: ReturnType<typeof facilityMapFixture>) => { v.result.candidates[0].selected_entry_index = 20 },
      (v: ReturnType<typeof facilityMapFixture>) => { delete v.pool.entrances!['14'] },
    ]) {
      const content = facilityMapFixture()
      change(content)
      expect(facilityComparisonMapModel(content)).toMatchObject({ available: false, referencePoints: [] })
    }
  })
  it('新候选出现才折叠旧空间分析，保留原内容和独有候选', () => {
    const content = <span>原活动区域候选及历史空间图</span>
    const current = renderToStaticMarkup(<LegacyCandidateReference currentFacility>{content}</LegacyCandidateReference>)
    expect(current).toContain('<details>')
    expect(current).not.toContain('<details open')
    expect(current).not.toContain('原活动区域候选及历史空间图') // Mount maps only after expansion.
    const legacy = renderToStaticMarkup(<LegacyCandidateReference currentFacility={false}>{content}</LegacyCandidateReference>)
    expect(legacy).not.toContain('<details')
    expect(legacy).toContain('原活动区域候选及历史空间图')
  })
})
