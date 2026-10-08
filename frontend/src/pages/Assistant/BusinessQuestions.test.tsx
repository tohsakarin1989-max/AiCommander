import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import BusinessQuestions, { businessEntryContext } from './BusinessQuestions'
import EvidenceAnswer, { answerValid } from './EvidenceAnswer'
import type { EvidenceAnswer as Answer, QueryCard } from '../../services/intelligentQueries'

const cards: QueryCard[] = [{ tool: 'business_recent_changes', state: 'ready', data: {} }]
const answer: Answer = { schema_version: 'business-answer-8.4-1', summary: '旧兼容摘要', findings: [], information_gaps: ['案发时间仍未知'],
  boundary: '不推定实际发生率', direct_answer: '本期新增登记含1条历史补录，不等于近期案发增加。', completeness: 'partial',
  evidence: [{ text: '历史发现时间早于本期', evidence_refs: ['case:7'] }],
  differences: [{ text: '发现与录入口径不同', evidence_refs: ['case_revision:8'] }], unanswered: ['未掌握真实案发时间'],
  time_scope_versions: { source_context: { area_id: 1, time_basis: 'discovery' }, algorithm_version: '8.4-test',
    scope_version: '1', answered_at: '2026-10-08T00:00:00Z', source_versions: [{ kind: 'case', id: 7, version: 'v1' }] } }

describe('三个明确业务问题', () => {
  it('继承当前对象，不发送原文和客户端授权；未点击不启动', () => {
    expect(businessEntryContext({ source_case_id: 9, filters: { operational_area_id: 2 } }, '11'))
      .toEqual({ context: { case_id: 9, asset_id: 11, area_id: 2 } })
    const run = vi.fn()
    const html = renderToStaticMarkup(<BusinessQuestions initial={{ source_case_id: 9, filters: {} }} disabled={false} onRun={run} />)
    expect(html).toContain('这条记录有什么历史参考'); expect(html).toContain('最近发生了哪些实质变化')
    expect(run).not.toHaveBeenCalled()
  })
  it('不能丢掉当前列表筛选或错误设施编号后扩大到全库', () => {
    expect(businessEntryContext({ filters: { keyword: '管线' } }).error).toContain('不能忽略')
    expect(businessEntryContext(undefined, 'broken').error).toContain('未退回区域查询')
  })
  it('回答状态独立于工具运行成功，页面完整呈现反向与缺口', () => {
    expect(answerValid(answer, cards)).toBe(true)
    const html = renderToStaticMarkup(<EvidenceAnswer answer={answer} cards={cards} />)
    expect(html).toContain('部分回答'); expect(html).toContain(answer.direct_answer!)
    expect(html).toContain('发现与录入口径不同'); expect(html).toContain('未掌握真实案发时间')
    expect(html).toContain('8.4-test'); expect(html).not.toContain('研判完成')
  })
  it('缺少回答完整度或证据结构时不当成成功', () => {
    expect(answerValid({ ...answer, completeness: undefined }, cards)).toBe(false)
    expect(answerValid({ ...answer, evidence: [{ text: '没有引用' }] }, cards)).toBe(false)
    expect(renderToStaticMarkup(<EvidenceAnswer answer={{ ...answer, time_scope_versions: null }} cards={cards} />))
      .toContain('答案依据结构不完整')
  })
})
