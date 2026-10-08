import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { isCaseHistoryResult, type CaseHistoryResult, type HistoryProcessComparison } from './caseHistory'
import { CaseHistoryContent } from '../pages/Cases/CaseHistoryReferences'

const fixture = (): CaseHistoryResult => ({ schema_version: 'case-history-6.3-1', source_case_id: 2, state: 'partial',
  mode: 'lexical_fallback', semantic_index_state: 'not_enabled', retrieval_mode: 'fragment_index', index_state: 'partial',
  coverage: { authorized_cases: 30, scanned_cases: 1, matched_sources: 1, complete: false, indexed_cases: 20,
    missing_index_cases: 10, indexed_fragments: 60, recalled_fragments: 1, validated_fragments: 1,
    invalidated_fragments: 0, recall_limit: 100, recall_truncated: false },
  boundary: '相似不等于事实关联', items: [{ source_type: 'case', source_id: 1, case_id: 1, case_number: 'SYN', title: '合成早期案例',
    snippet: '未转运原油', route: '/cases?caseId=1', shared_conditions: [['action', '转运', 'negated']],
    different_conditions: [], unmatched_query_conditions: [], score: 0.01, score_kind: 'rrf', profile_state: 'ready',
    versions: { source_revision_id: 12 }, lexical_rank: 1,
    fragment: { id: 'fragment', kind: 'process', source_revision_id: 12,
      reference: { field: 'description', source_sha256: 'a'.repeat(64), start: 2000, end: 2005, quote: '未转运原油' } } }] })

function comparison(): HistoryProcessComparison {
  const ref = (quote: string, revision: number) => ({ field: 'description', source_sha256: 'b'.repeat(64), start: 0,
    end: quote.length, quote, source_revision_id: revision })
  return { version: 'history-process-comparison-7.5-1', state: 'ready', reason: '规范化动作对照', boundary: '不确认事实链，未记载不等于未发生',
    current: { case_id: 2, profile_id: 'current-profile', source_revision_id: 20, source_hash: 'c'.repeat(64) },
    historical: { case_id: 1, profile_id: 'historical-profile', source_revision_id: 12, source_hash: 'd'.repeat(64) },
    pairs: [{ action: '转运', relation: 'counter', current: { event_id: 'current-event', action_kind: 'stated', statement_kind: 'stated',
      reference: ref('转运原油', 20), action_reference: ref('转运', 20) },
      historical: { event_id: 'old-event', action_kind: 'negated', statement_kind: 'negated', reference: ref('未转运原油', 12),
        action_reference: { ...ref('转运', 12), start: 1, end: 3 } },
      shared_conditions: [], counter_conditions: [['oil', '原油', 'negated']], current_only_conditions: [['oil', '原油', 'stated']],
      historical_only_conditions: [], current_missing_dimensions: ['time'], historical_missing_dimensions: ['location'] }],
    unmatched_current: [], unmatched_historical: [], coverage: { complete: true, pair_limit: 24, omitted_pairs: 0 } }
}

describe('片段检索契约', () => {
  it('双侧环节显示独立原文与修订，反向资料不会进入共同陈述栏', () => {
    const data = fixture(); data.items[0].process_comparison = comparison()
    expect(isCaseHistoryResult(data)).toBe(true)
    const html = renderToStaticMarkup(<MemoryRouter><CaseHistoryContent result={data} /></MemoryRouter>)
    for (const text of ['反向表述（不计支持）', '当前案 · 原文陈述', '历史案 · 原文否定', '修订 #20', '修订 #12', '未记载不等于未发生']) expect(html).toContain(text)
    expect(html).not.toContain('共同明确陈述（不是事实链）')
    expect(html).not.toContain('匹配概率')
  })
  it('源案错绑、极性晋升和原文跨度错误使新字段整体不可读；旧字段仍兼容', () => {
    const data = fixture(); data.items[0].process_comparison = comparison()
    data.items[0].process_comparison.current.case_id = 90
    expect(isCaseHistoryResult(data)).toBe(false)
    data.items[0].process_comparison = comparison()
    data.items[0].process_comparison.pairs[0].relation = 'stated_match'
    expect(isCaseHistoryResult(data)).toBe(false)
    data.items[0].process_comparison = comparison()
    data.items[0].process_comparison.pairs[0].current.reference.end = 90
    expect(isCaseHistoryResult(data)).toBe(false)
    delete data.items[0].process_comparison
    expect(isCaseHistoryResult(data)).toBe(true)
  })
  it('显示长文后段出处与真实索引覆盖，不以候选数冒充逐案扫描', () => {
    const data = fixture()
    expect(isCaseHistoryResult(data)).toBe(true)
    const html = renderToStaticMarkup(<MemoryRouter><CaseHistoryContent result={data} /></MemoryRouter>)
    for (const value of ['索引尚未就绪', '字符 2001 至 2005', '原文否定', '不是全库统计', '词项']) expect(html).toContain(value)
    expect(html).not.toContain('没有匹配')
  })
  it('片段跨度或索引计数损坏不能作为可读成果', () => {
    const data = fixture()
    data.items[0].fragment!.reference.end = 9000
    expect(isCaseHistoryResult(data)).toBe(false)
    const other = fixture()
    other.coverage.indexed_cases = -1
    expect(isCaseHistoryResult(other)).toBe(false)
  })
})
