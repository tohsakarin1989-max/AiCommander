import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { QueryResult } from './QueryResult'
import { MemoryRouter } from 'react-router-dom'

const hypothesis = { id: 'h', title: '待核查区域', claim: '候选解释', rule_support: 60,
  supporting_evidence: ['支持内容'], counter_evidence: ['反向内容'], information_gaps: ['缺口内容'],
  evidence_refs: ['case:1'], boundary: '不是正式事实' }
function render(item: Record<string, unknown>) {
  return renderToStaticMarkup(<QueryResult card={{ tool: 'summarize_results', state: 'ready',
    data: { total: 1, items: [{ run_id: 'r', ...item }] } }} />)
}

describe('existing insight result presentation', () => {
  it('preserves negation, source quote and batch-only meaning for semantic profiles', () => {
    const html = renderToStaticMarkup(<MemoryRouter><QueryResult card={{ tool: 'find_case_profiles', state: 'ready',
      data: { total: 1, items: [{ case_id: 1, case_number: 'ONE', content_state: 'ready', profile_version: 2,
        assertions: [{ value: '罐车', kind: 'negated', reference: { field: 'description', quote: '未发现罐车',
          start: 0, end: 5, source_sha256: 'original-hash' } }] }],
        batch_patterns: [{ value: '罐车', kind: 'negated', case_count: 1 }] } }} /></MemoryRouter>)
    for (const text of ['原文否定', '未发现罐车', 'original-hash', '非全库统计']) expect(html).toContain(text)
  })
  it('shows frozen road distances and versions without claiming case totals or trajectories', () => {
    const html = renderToStaticMarkup(<MemoryRouter><QueryResult card={{ tool: 'find_road_results', state: 'ready',
      data: { returned: 1, items: [{ operation: 'route', case_id: 1, distance_m: 1500,
        target: { name: '合成井' }, alternative_count: 0, map_snapshot_id: 'map-1', policy_revision: 2,
        artifact_sha256: 'artifact-hash', graph_sha256: 'graph-hash',
        boundary: '不是实际轨迹', detour_reference: { basis: 'route_geometry_endpoints', status: 'available',
          straight_distance_m: 1000, road_distance_m: 1500, ratio: 1.5, additional_distance_m: 500 } }] } }} /></MemoryRouter>)
    for (const text of ['合成井', '1.50 公里', '不是案件总数', '不是实际轨迹', 'map-1', 'artifact-hash'])
      expect(html).toContain(text)
  })
  it('shows actual candidates with evidence and no probability claim', () => {
    const html = render({ content_state: 'ready', hypotheses: [hypothesis], summary: '成果摘要' })
    for (const text of ['成果摘要', '候选解释', '支持内容', '反向内容', '缺口内容', 'case:1', '不是准确概率']) {
      expect(html).toContain(text)
    }
  })
  it('does not render unavailable content and handles legacy metadata', () => {
    const html = render({ content_state: 'unavailable', hypotheses: [hypothesis], summary: '不可展示摘要' })
    expect(html).not.toContain('候选解释')
    expect(html).not.toContain('不可展示摘要')
    expect(html).toContain('正文暂不展示')
    expect(render({})).toContain('历史查询仅记录数量和版本')
  })
  it('escapes text instead of treating evidence as HTML', () => {
    const html = render({ content_state: 'ready', hypotheses: [{ ...hypothesis, claim: '<script>x</script>' }] })
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })
})
