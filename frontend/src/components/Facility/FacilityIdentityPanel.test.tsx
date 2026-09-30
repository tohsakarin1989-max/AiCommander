import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ComputabilityContent, FacilityIdentityContent, FacilityTemporalContent, facilityLocalTime, facilityQueryInstant } from './FacilityIdentityPanel'
import type { FacilityTemporalContext } from '../../services/facilityAnalysis'

const temporal: FacilityTemporalContext = { valid_at: '2026-08-01T00:00:00Z', known_at: '2026-09-01T00:00:00Z', state: 'ready', version_id: 9,
  valid_from: '2026-07-01T00:00:00Z', valid_to: null, recorded_at: '2026-08-10T04:00:00Z', boundary: '双时间不互相替代',
  snapshot: { name: '历史生产名称', asset_type: 'well', attributes: { oil_type: '原油', production_output: '5 升' } } }

describe('设施身份、双时间与计算资料表达', () => {
  it('历史有效资料与收到时间分别展示，不用最新值代替未知或冲突', () => {
    const html = renderToStaticMarkup(<FacilityTemporalContent temporal={temporal} />)
    expect(html).toContain('业务有效起始'); expect(html).toContain('系统接收时间'); expect(html).toContain('2026-08-10 12:00')
    expect(html).toContain('历史生产名称'); expect(html).toContain('5 升')
    for (const state of ['unknown', 'conflict'] as const) {
      const failed = renderToStaticMarkup(<FacilityTemporalContent temporal={{ ...temporal, state }} />)
      expect(failed).not.toContain('历史生产名称'); expect(failed).not.toContain('5 升')
      expect(failed).toContain(state === 'conflict' ? '未替用户选择' : '未回退为当前')
    }
  })
  it('受限生产版本或身份不泄漏误传快照、来源名称与数量', () => {
    const restricted = renderToStaticMarkup(<FacilityTemporalContent temporal={{ ...temporal, state: 'restricted' }} />)
    expect(restricted).not.toContain('历史生产名称'); expect(restricted).not.toContain('2026-08-10')
    const identity = renderToStaticMarkup(<FacilityIdentityContent identity={{ asset_id: 8, state: 'restricted', boundary: '不应显示', items: [{ identity_id: 1, source_id: 2, source_name: '机密台账', source_record_id: 'SECRET', name: '不应显示', decision_id: null, status: 'bound' }] }} />)
    expect(identity).toContain('来源身份资料受限'); expect(identity).not.toContain('SECRET'); expect(identity).not.toContain('不应显示')
  })
  it('未识别来源编号明确待核，不展示生成标识为真实台账编号', () => {
    const html = renderToStaticMarkup(<FacilityIdentityContent identity={{ asset_id: 8, state: 'ready', boundary: '', items: [{ identity_id: 1, source_id: 2, source_name: '台账', source_record_id: 'generated-id', identity_kind: 'unidentified', name: '同名井', decision_id: null, status: 'source_identified' }] }} />)
    expect(html).toContain('编号待核'); expect(html).not.toContain('generated-id'); expect(html).not.toContain('确认关联')
  })
  it('缺失、待核、断开、权限、过期及服务故障不是同一种问题', () => {
    const html = renderToStaticMarkup(<ComputabilityContent data={{ state: 'partial', boundary: '不是导航路线', checks: [
      { key: 'entry', label: '入口', state: 'missing', detail: '未登记入口' },
      { key: 'link', label: '连接', state: 'disconnected', detail: '未连接' },
      { key: 'verified', label: '核验', state: 'unverified', detail: '尚未核验' },
      { key: 'access', label: '许可', state: 'restricted', detail: '秘密许可27条', evidence_refs: ['secret:27'] },
      { key: 'conditions', label: '条件', state: 'expired', detail: '已过期' },
      { key: 'service', label: '服务', state: 'unavailable', detail: '暂不可用' },
    ] }} />)
    for (const label of ['资料缺失', '待核验', '未连接', '权限受限', '资料过期', '服务暂不可用']) expect(html).toContain(label)
    expect(html).toContain('不代表已经算出可达路线'); expect(html).not.toContain('秘密许可27条'); expect(html).not.toContain('secret:27')
  })
  it('北京时间控件转换UTC并拒绝非法日期，清空不强加当前时间参数', () => {
    expect(facilityLocalTime('2026-09-01T00:00:00Z')).toBe('2026-09-01T08:00')
    expect(facilityQueryInstant('2026-09-01T08:00')).toBe('2026-09-01T00:00:00.000Z')
    expect(facilityQueryInstant('')).toBeNull()
    expect(() => facilityQueryInstant('2026-02-30T08:00')).toThrow()
  })
})
