import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import CaseHistoryReferences, { CaseHistoryContent, CaseHistoryPreview, historyReferenceUnavailable } from './CaseHistoryReferences'
import type { CaseHistoryResult } from '../../services/caseHistory'

const queryState = vi.hoisted(() => ({ data: undefined as CaseHistoryResult | undefined, error: false, epoch: 1, keys: [] as unknown[][] }))
vi.mock('react-router-dom', () => ({ Link: ({ children, to }: { children: ReactNode; to: string }) => <a href={to}>{children}</a>,
  useSearchParams: () => [new URLSearchParams('caseId=9')] }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 7 }, sessionEpoch: queryState.epoch }) }))
vi.mock('@tanstack/react-query', () => ({ useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
  queryState.keys.push(queryKey)
  return { data: queryState.data, isError: queryState.error, isPending: false, isFetching: false, refetch: vi.fn() }
} }))

const result: CaseHistoryResult = {
  schema_version: 'case-history-5.1-1', source_case_id: 9, state: 'ready', mode: 'lexical_fallback',
  semantic_index_state: 'not_enabled', coverage: { authorized_cases: 621, scanned_cases: 621, matched_sources: 1, complete: true },
  items: [{ source_type: 'case', source_id: 1, case_id: 1, case_number: 'OLD', title: '旧案件', snippet: '旧资料', route: '/cases?caseId=1',
    shared_conditions: [['action', '转运', 'negated']], different_conditions: [], unmatched_query_conditions: [],
    score: 0.9, score_kind: 'retrieval_support_not_probability', profile_state: 'current', versions: { source_text_hash: 'version-1' } }],
  boundary: '不成为当前案件事实',
}
describe('历史参考展示', () => {
  beforeEach(() => { queryState.data = undefined; queryState.error = false; queryState.epoch = 1; queryState.keys = [] })
  it('历史上下文不允许自动调用只有当前索引的参考接口', () => {
    for (const query of ['known_at=2026-08-01T00:00:00Z', 'valid_at=2026-08-01T00:00:00Z', 'valid_from=2026-08-01T00:00:00Z', 'time_scope=frozen_result', 'knowledge_mode=as_known']) {
      expect(historyReferenceUnavailable(new URLSearchParams(query))).toBe(true)
    }
    expect(historyReferenceUnavailable(new URLSearchParams('caseId=3&case_page=4&time_scope=unknown'))).toBe(false)
  })
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
  it('录后概览直接显示最多三项已有参考，保留否定和来源返回位置', () => {
    const html = renderToStaticMarkup(<CaseHistoryPreview context={new URLSearchParams('caseId=9&case_page=4&case_page_size=20')}
      result={{ ...result, items: [1, 2, 3, 4].map(id => ({ ...result.items[0], source_id: id, title: `参考${id}`, route: `/cases?caseId=${id}` })) }} />)
    expect(html).toContain('参考3'); expect(html).not.toContain('参考4')
    expect(html).toContain('转运（原文否定）'); expect(html).toContain('return_to=')
    expect(html).toContain('不另建分析任务'); expect(html).not.toContain('自动确认')
  })
  it('权限读取失败时隐藏已有缓存，不能泄露标题、数量或误报无匹配', () => {
    queryState.data = result
    expect(renderToStaticMarkup(<CaseHistoryReferences caseId={9} />)).toContain('旧案件')
    queryState.error = true
    const html = renderToStaticMarkup(<CaseHistoryReferences caseId={9} />)
    expect(html).toContain('历史检索暂不可用')
    for (const value of ['旧案件', '621', '未找到匹配', 'version-1']) expect(html).not.toContain(value)
    queryState.error = false
    const other = renderToStaticMarkup(<CaseHistoryReferences caseId={10} />)
    expect(other).toContain('来源尚未确认'); expect(other).not.toContain('旧案件')
  })
  it('自动混合参考隔离用户会话与源案修订的缓存', () => {
    renderToStaticMarkup(<CaseHistoryReferences caseId={9} revision="r1" />)
    queryState.epoch = 2
    renderToStaticMarkup(<CaseHistoryReferences caseId={9} revision="r2" />)
    expect(queryState.keys).toEqual([
      ['case-history', 9, 7, 1, 'r1', false, 'mixed-8.1'],
      ['case-history', 9, 7, 2, 'r2', false, 'mixed-8.1'],
    ])
  })
})
