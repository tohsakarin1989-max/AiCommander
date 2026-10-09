import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import EvidenceAnswer, { answerValid } from './EvidenceAnswer'
import { businessEntryContext } from './BusinessQuestions'
import { presetArguments } from './QueryPresets'
import type { EvidenceAnswer as Answer } from '../../services/intelligentQueries'

describe('v9 unified question and answer contract', () => {
  it('uses one complete answer view for generic and rule answers', () => {
    const answer: Answer = { schema_version: 'query-answer-6.4-1', answer_contract_version: 'answer-snapshot-9.3-1',
      summary: '本期两条记录，尚不能解释变化来源。', direct_answer: '本期两条记录，尚不能解释变化来源。',
      completeness: 'partial', findings: [{ text: '两条记录', card_index: 0, evidence_refs: ['query_card:0'] }],
      information_gaps: ['缺少变化来源'], unanswered: ['缺少变化来源'], evidence: [{ text: '两条记录', evidence_refs: ['query_card:0'] }],
      differences: [], boundary: '不认定案件关系', time_scope: { time_basis: 'discovery', timezone: 'Asia/Shanghai' },
      answer_requirements: { required: ['total', 'origins'], satisfied: ['total'], missing: ['origins'] },
      capabilities: { rule_answering: 'enabled', model_enhancement: 'not_used', model_acceptance: 'not_established' },
      time_scope_versions: { source_context: { time_basis: 'discovery' }, algorithm_version: 'v9', scope_version: 'scope',
        answered_at: '2026-10-09', source_versions: [] } }
    const cards = [{ tool: 'count_cases', state: 'ready', data: { count: 2 } }]
    expect(answerValid(answer, cards)).toBe(true)
    const html = renderToStaticMarkup(<EvidenceAnswer cards={cards} answer={answer} />)
    expect(html).toContain('部分回答')
    expect(html).toContain('发现／查获')
    expect(html).toContain('工具执行完成不等于问题已完整回答')
    expect(html).toContain('未使用模型增强')
  })
  it('inherits explicit time basis without silently dropping other filters', () => {
    expect(businessEntryContext({ filters: { operational_area_id: 1, time_basis: 'entry' } }).context)
      .toEqual({ area_id: 1, time_basis: 'entry' })
    expect(businessEntryContext({ filters: { keyword: '不能丢弃', time_basis: 'entry' } }).error).toBeTruthy()
    expect(presetArguments('case_count', { timeBasis: 'discovery' }).arguments.time_basis).toBe('discovery')
  })
})
