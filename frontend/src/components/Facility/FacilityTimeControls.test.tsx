import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { makeFacilityTimeSelection, facilityLocalTime, facilityQueryInstant } from './FacilityTimeControls'
import { FacilityTemporalContent } from './FacilityIdentityPanel'
import type { FacilityTemporalContext } from '../../services/facilityAnalysis'

describe('完整业务时间和历史获知口径', () => {
  it('无编辑再提交不截断秒、毫秒及服务器微秒截止', () => {
    const original = { start: '2026-08-01T00:00:40.123456Z', end: '2026-08-01T00:01:20.987654Z', known: '2026-09-01T12:34:56.789123Z' }
    const selection = makeFacilityTimeSelection({ period: 'interval', mode: 'as_known', start: facilityLocalTime(original.start), end: facilityLocalTime(original.end), known: facilityLocalTime(original.known), original })
    expect(selection).toMatchObject({ valid_from: original.start, valid_to: original.end, known_at: original.known })
    expect(facilityQueryInstant('2026-08-01T08:00:40.123')).toBe('2026-08-01T00:00:40.123Z')
  })
  it('区间保留两端；回看历史不发送旧获知时间', () => {
    expect(makeFacilityTimeSelection({ period: 'interval', mode: 'retrospective', start: '2026-08-01T08:00', end: '2026-08-03T08:00', known: '2026-08-04T08:00' })).toEqual({
      valid_at: null, valid_from: '2026-08-01T00:00:00.000Z', valid_to: '2026-08-03T00:00:00.000Z', known_at: null, knowledge_mode: 'retrospective',
    })
    expect(() => makeFacilityTimeSelection({ period: 'interval', mode: 'retrospective', start: '2026-08-01T08:00', end: '', known: '' })).toThrow()
    expect(() => makeFacilityTimeSelection({ period: 'point', mode: 'as_known', start: '2026-08-01T08:00', end: '', known: '' })).toThrow()
  })
  it('部分覆盖、迟到补录与不同区间分别展示；未知不显示误传值', () => {
    const temporal: FacilityTemporalContext = { state: 'partial', valid_at: null, known_at: '2026-10-01T00:00:00Z', boundary: '不是案发时实际情况确认',
      query_interval: { from: '2026-08-01T00:00:00Z', to: '2026-08-03T00:00:00Z' }, knowledge_mode: 'retrospective', coverage: 'partial', late_supplement: true,
      groups: { water_cut: { state: 'partial', coverage: 'partial', gaps: ['缺少后半段资料'], segments: [
        { from: '2026-08-01T00:00:00Z', to: '2026-08-02T00:00:00Z', end_inclusive: false, state: 'ready', values: { water_cut: 20 }, evidence_refs: ['decision:2'], late_supplement: true },
        { from: '2026-08-02T00:00:00Z', to: '2026-08-03T00:00:00Z', end_inclusive: true, state: 'unknown', values: { secret: '错误缓存' }, evidence_refs: [] },
      ] } } }
    const html = renderToStaticMarkup(<FacilityTemporalContent temporal={temporal} />)
    for (const value of ['部分区间有资料', '后来补录', '缺少后半段资料', 'decision:2', '未使用中点']) expect(html).toContain(value)
    expect(html).not.toContain('错误缓存')
    const restricted = renderToStaticMarkup(<FacilityTemporalContent temporal={{ ...temporal, state: 'restricted' }} />)
    expect(restricted).not.toContain('decision:2'); expect(restricted).not.toContain('2026-08-01')
  })
})
