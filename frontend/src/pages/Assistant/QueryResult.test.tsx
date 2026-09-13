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
  it('reuses historical reference presentation with negation, differences and source versions', () => {
    const html = renderToStaticMarkup(<MemoryRouter><QueryResult card={{ tool: 'find_history', state: 'ready',
      data: { schema_version: 'case-history-5.1-1', source_case_id: 9, state: 'ready', mode: 'lexical_fallback',
        semantic_index_state: 'not_enabled', coverage: { authorized_cases: 621, scanned_cases: 621, matched_sources: 1, complete: true },
        boundary: '历史参考不成为当前案件事实', items: [{ source_type: 'case', source_id: 1, case_id: 1,
          title: '早期历史案件', snippet: '未转运。', route: '/cases?caseId=1', versions: { source_text_hash: 'frozen-hash' },
          shared_conditions: [['action', '转运', 'negated']], different_conditions: [['oil', '原油', 'uncertain']],
          unmatched_query_conditions: [], score: 0.9 }] } }} /></MemoryRouter>)
    for (const text of ['早期历史案件', '转运（原文否定）', '原油（不确定）', 'frozen-hash', '621', '语义向量索引未启用'])
      expect(html).toContain(text)
    expect(html).not.toContain('90%')
    expect(html).not.toContain('共 621 条')
  })
  it('does not render invalid historical source links or report incomplete scans as no match', () => {
    const partial = { schema_version: 'case-history-5.1-1', state: 'partial', mode: 'lexical_fallback',
      semantic_index_state: 'not_enabled', coverage: { authorized_cases: 621, scanned_cases: 10, matched_sources: 0, complete: false },
      boundary: '仅供参考', items: [] }
    const html = renderToStaticMarkup(<QueryResult card={{ tool: 'find_history', state: 'partial', data: partial }} />)
    expect(html).toContain('未完成全部范围')
    expect(html).not.toContain('没有匹配数据')
    const malformed = renderToStaticMarkup(<QueryResult card={{ tool: 'find_history', state: 'ready',
      data: { ...partial, items: [{ title: '恶意地址', route: 'https://external.invalid' }] } }} />)
    expect(malformed).toContain('历史参考结构或来源不完整')
    expect(malformed).not.toContain('external.invalid')
  })
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
