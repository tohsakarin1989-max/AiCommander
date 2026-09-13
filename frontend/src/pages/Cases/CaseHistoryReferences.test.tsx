import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { CaseHistoryContent } from './CaseHistoryReferences'
import type { CaseHistoryResult } from '../../services/caseHistory'

vi.mock('react-router-dom', () => ({ Link: ({ children, to }: { children: ReactNode; to: string }) => <a href={to}>{children}</a> }))

const result: CaseHistoryResult = {
  schema_version: 'case-history-5.1-1', source_case_id: 9, state: 'ready', mode: 'lexical_fallback',
  semantic_index_state: 'not_enabled', coverage: { authorized_cases: 621, scanned_cases: 621, matched_sources: 1, complete: true },
  items: [{ source_type: 'case', source_id: 1, case_id: 1, case_number: 'OLD', title: '旧案件', snippet: '旧资料', route: '/cases?caseId=1',
    shared_conditions: [['action', '转运', 'negated']], different_conditions: [], unmatched_query_conditions: [],
    score: 0.9, score_kind: 'retrieval_support_not_probability', profile_state: 'current', versions: { source_text_hash: 'version-1' } }],
  boundary: '不成为当前案件事实',
}
describe('历史参考展示', () => {
  it('保留否定、版本与模型未启用说明，不显示准确概率', () => {
    const html = renderToStaticMarkup(<CaseHistoryContent result={result} />)
    expect(html).toContain('转运（原文否定）')
    expect(html).toContain('语义向量索引未启用')
    expect(html).toContain('version-1')
    expect(html).toContain('/cases?caseId=1')
    expect(html).not.toContain('90%')
  })
  it('部分空结果不能表述为全库无匹配', () => {
    const html = renderToStaticMarkup(<CaseHistoryContent result={{ ...result, state: 'partial', items: [], coverage: { ...result.coverage, scanned_cases: 100, complete: false } }} />)
    expect(html).toContain('未完成全部范围')
    expect(html).not.toContain('未找到匹配')
  })
  it('模型故障明确保留词项结果，不冒充模型未配置', () => {
    const html = renderToStaticMarkup(<CaseHistoryContent result={{ ...result, semantic_index_state: 'unavailable' }} />)
    expect(html).toContain('本地语义模型暂不可用')
    expect(html).toContain('旧案件')
    expect(html).not.toContain('语义向量索引未启用')
  })
  it('联合检索缺少向量时说明不完整，不将相似程度写成概率', () => {
    const html = renderToStaticMarkup(<CaseHistoryContent result={{ ...result, state: 'partial', mode: 'hybrid_local',
      semantic_index_state: 'partial', coverage: { ...result.coverage, complete: false } }} />)
    expect(html).toContain('部分资料尚无当前版本向量')
    expect(html).toContain('名次融合')
    expect(html).toContain('不是准确概率')
    expect(html).toContain('未完成全部范围')
  })
})
