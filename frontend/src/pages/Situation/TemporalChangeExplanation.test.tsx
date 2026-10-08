import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import type { SituationBriefResult } from '../../services/intelligenceFlow'
import TemporalChangeExplanation from './TemporalChangeExplanation'

type Comparison = NonNullable<SituationBriefResult['comparison_snapshot']>
const legacy: Comparison = { timezone: 'Asia/Shanghai',
  previous: { start: '2026-08-01', end: '2026-09-01', case_count: 1, profile_versions_generated: 0 },
  current: { start: '2026-09-01', end: '2026-10-01', case_count: 0, profile_versions_generated: 1 } }
const render = (comparison: Comparison) => renderToStaticMarkup(<MemoryRouter><TemporalChangeExplanation comparison={comparison} /></MemoryRouter>)

describe('多时间口径与变化说明', () => {
  it('旧材料不会静默改用发现时间', () => {
    expect(render(legacy)).toContain('历史简报按原案发时间口径保留')
    expect(render(legacy)).not.toContain('本期登记变化')
  })
  it('补录、修改、删除分列并能打开已授权来源', () => {
    const html = render({ ...legacy, time_basis: 'discovery', time_basis_label: '发现／查获',
      change_origins: {
        recent_registered: { case_ids: [], count: 0, label: '本期发现并录入' },
        late_entry: { case_ids: [17], count: 1, label: '补录历史情况' },
        entry_time_uncertain: { case_ids: [], count: 0, label: '时间未知' },
        corrections: { count: 1, label: '修订次数', items: [{ case_id: 17, revision_id: 33, change_id: 20, change_type: 'updated' }] },
        withdrawals: { audit_ids: [9], count: 1, label: '撤回次数' }, boundary: '各行不能相加。' } })
    expect(html).toContain('/cases?caseId=17'); expect(html).toContain('修订 33')
    expect(html).toContain('补录历史情况'); expect(html).toContain('不展示已删除原文')
    expect(html).not.toContain('/cases?caseId=9')
  })
  it('空集合不显示0%缺失；不可比历史不显示旧来源', () => {
    const html = render({ ...legacy, time_basis: 'discovery', quality: { denominator: 0,
      denominator_label: '当前授权范围', unknown_time_count: 0, unknown_time_ratio: null,
      unclear_place_count: 0, unclear_place_ratio: null, unstructured_method_count: 0,
      unstructured_method_ratio: null, boundary: '未知不能当作否定。' },
      snapshot_change: { state: 'incomparable', reason: '旧资料受限', items: [{ kind: 'test', label: '隐藏', case_ids: [999] }] } })
    expect(html).toContain('无分母，不计算比例'); expect(html).toContain('旧资料受限')
    expect(html).not.toContain('caseId=999')
  })
  it('数量相同仍展示条件变化；否定保持否定，不可比不显示条件计数', () => {
    const semantics = { state: 'comparable', boundary: '表述不等于已核实事实', information_gaps: [],
      previous: { case_count: 1, readable_case_count: 1 }, current: { case_count: 1, readable_case_count: 1 },
      changes: [{ category: 'method', value: '软管', kind: 'negated', previous_count: 0, current_count: 1, case_count_change: 1 }] }
    const comparison = { ...legacy, time_basis: 'discovery' as const, semantic_changes: semantics }
    const html = render(comparison)
    expect(html).toContain('软管'); expect(html).toContain('否定表述'); expect(html).toContain('open=""')
    const unavailable = render({ ...comparison, semantic_changes: { ...semantics, state: 'incomparable' } })
    expect(unavailable).toContain('两期画像条件不同'); expect(unavailable).not.toContain('软管')
  })
})
