import { describe, expect, it } from 'vitest'
import { facilityEntryPatch, facilityHasUsablePoint, intakeCapabilityLabel, intakeEvidenceLabel } from './caseEntryAssistance'
import type { CaseStructurePreview } from '../../types'

describe('录入辅助只复用可靠已知信息', () => {
  const asset = { id: 3, name: '同名井', external_id: 'W-3', asset_type: 'well', address: '合成井场', verified: true, latitude: 46, longitude: 125 }
  it('仅选地点文字不悄悄改变坐标或业务事实', () => {
    expect(facilityEntryPatch(asset)).toEqual({ location: '同名井（合成井场）' })
    expect(facilityEntryPatch(asset, true)).toEqual({ location: '同名井（合成井场）', latitude: 46, longitude: 125 })
  })
  it('未核验或面要素不能把中心坐标当精确案发点', () => {
    expect(facilityHasUsablePoint({ ...asset, verified: false })).toBe(false)
    expect(facilityEntryPatch({ ...asset, geometry_type: 'Polygon' }, true)).toEqual({ location: '同名井（合成井场）' })
    expect(facilityHasUsablePoint({ ...asset, latitude: NaN })).toBe(false)
  })
  it('不把规则结果说成模型已连接或准确率', () => {
    expect(intakeCapabilityLabel('deterministic_fallback')).toContain('不代表模型已启用')
    expect(intakeCapabilityLabel('llm_failed')).toContain('模型本次未完成')
    expect(intakeCapabilityLabel('llm_success')).toContain('仍需核对原文')
  })
  it('无依据或未验证锚点不伪装成正常原文引用', () => {
    const preview = { evidence_anchors: [{ field: 'location', text: '', reference_status: 'unverified' }] } as CaseStructurePreview
    expect(intakeEvidenceLabel(preview, 'location')).toBe('未定位到原文依据，请核对')
    expect(intakeEvidenceLabel({ ...preview, evidence_anchors: [{ id: 'a', field: 'location', text: '合成地点', source: 'rules', reference_status: 'verified' }] }, 'location')).toContain('原文依据：合成地点')
  })
})
