import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import QueryPresets, { presetArguments } from './QueryPresets'
import EvidenceAnswer, { answerValid } from './EvidenceAnswer'
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 1 }, sessionEpoch: 1 }) }))
vi.mock('../../components/CaseSearch', () => ({ default: () => <p>完整案件检索</p> }))
vi.mock('../../components/Facility/FacilitySearch', () => ({ default: () => <p>完整设施检索</p> }))

describe('确定性查询与证据化回答', () => {
  it('沿用已选案件/范围，预设不是只填示例文字', () => {
    const context = { source_case_id: 8, filters: { operational_area_id: 3, keyword: '管线' } }
    expect(presetArguments('case_count', {}, context).arguments).toEqual({ case_id: 8, operational_area_id: 3, keyword: '管线' })
    expect(presetArguments('case_process', { caseId: '99' }, context).arguments.case_id).toBe(8)
    const html = renderToStaticMarkup(<QueryPresets disabled={false} context={context} onRun={() => {}} />)
    expect(html).toContain('使用已选择案件 #8')
    expect(html).toContain('运行此项查询')
    expect(html).toContain('不依赖模型')
  })
  it('历史时点和覆盖条件必须明确，不自动猜测', () => {
    expect(() => presetArguments('facility_history', { assetId: '3' })).toThrow('业务适用时间')
    expect(() => presetArguments('coverage_scenario', {})).toThrow('明确辖区')
    expect(() => presetArguments('coverage_scenario', { area: '1', asOf: '2026-09-30T01:00:00Z', disabled: 'abc' })).toThrow('登记编号')
    const value = presetArguments('coverage_scenario', { area: '1', asOf: '2026-09-30T01:00:00Z', disabled: '2,2,3' })
    expect(value.arguments.disabled_resource_ids).toEqual([2, 3])
  })
  it('设施入口可以更换检索结果，不再要求用户手填稳定编号', () => {
    const html = renderToStaticMarkup(<QueryPresets assetId="89" disabled={false} onRun={() => {}} />)
    expect(html).toContain('完整设施检索'); expect(html).toContain('从设施入口带入 #89')
    expect(html).not.toContain('设施稳定编号')
    expect(() => presetArguments('case_process', {})).toThrow('查找并选择案件')
  })
  it('不显示越界答案引用，不把原文指令当HTML', () => {
    const cards = [{ tool: 'count_cases', state: 'available', data: { count: 0 } }]
    const answer = { schema_version: 'query-answer-6.4-1', summary: '当前范围', boundary: '不自动认定事实', information_gaps: [],
      findings: [{ text: '<script>执行指令</script>', card_index: 0, evidence_refs: ['case:8'] }] }
    expect(answerValid(answer, cards)).toBe(true)
    const html = renderToStaticMarkup(<EvidenceAnswer cards={cards} answer={answer} />)
    expect(html).toContain('#query-card-0'); expect(html).not.toContain('<script>')
    answer.findings[0].card_index = 7
    expect(answerValid(answer, cards)).toBe(false)
    expect(renderToStaticMarkup(<EvidenceAnswer cards={cards} answer={answer} />)).toContain('答案依据结构不完整')
  })
})
