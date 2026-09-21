import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { QueryResult } from './QueryResult'

const base = {
  schema_version: 'profile-aggregate-5.3-1', total: 87,
  coverage: { complete: true, authorized_cases: 101, scanned_cases: 101 },
  statistics: { denominator: 101, matched: 87, unmatched: 10, unknown: 4,
    unavailable_profile_count: 4, unavailable_profile_ratio: 4 / 101 },
  patterns: [{ category: 'tool', value: '软管', kind: 'negated', case_count: 87 }],
  items: [{ case_id: 9, profile_version: 2 }], counterexamples: [{ case_id: 1 }], unknown_examples: [{ case_id: 2 }],
  missingness: [{ category: 'method', missing_count: 50, denominator: 97, ratio: 50 / 97 }],
  boundary: '不是正式串并案或真实团伙',
}
function render(data: Record<string, unknown>) {
  return renderToStaticMarkup(<MemoryRouter><QueryResult card={{ tool: 'aggregate_case_profiles',
    state: 'partial', data }} /></MemoryRouter>)
}

describe('whole corpus aggregate presentation', () => {
  it('separates full counts, negation and representative cases', () => {
    const html = render(base)
    for (const text of ['全部授权候选范围', '101', '87', '原文否定', '代表案例', '资料不足', '不是正式串并案']) {
      expect(html).toContain(text)
    }
    expect(html).toContain('/cases?caseId=9')
    expect(html).not.toContain('共 87 条')
    expect(html).not.toContain('准确概率')
  })
  it('does not label a partial scan as a census or unknown as negative', () => {
    const html = render({ ...base, coverage: { complete: false, authorized_cases: 101, scanned_cases: 3 } })
    expect(html).toContain('尚未遍历全部范围')
    expect(html).not.toContain('已遍历全部授权')
    expect(html).toContain('未知不按否定处理')
  })
  it('shows invalid structure and empty denominators without invented rates', () => {
    expect(render({ total: 0 })).toContain('统计结构不完整')
    const html = render({ ...base, statistics: { ...base.statistics, unavailable_profile_ratio: null } })
    expect(html).toContain('无可用分母')
    expect(html).not.toContain('NaN')
  })
})
