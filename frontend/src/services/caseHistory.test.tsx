import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { isCaseHistoryResult, type CaseHistoryResult } from './caseHistory'
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

describe('片段检索契约', () => {
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
