import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { caseDossierView, CaseDossierPanel, CaseQualityStatus } from './CaseDossier'
import type { CaseQuality } from '../../types'

export const qualityFixture: CaseQuality = {
  score: 66, level: 'medium', category_scores: {}, missing_required: [], warnings: [], recommendations: [], facts: {},
  validation: { status: 'valid', can_save: true, errors: [], warnings: [] },
  completeness: { status: 'partial', stage: 'recorded', gaps: [] },
  priority_gaps: ['时间', '地点', '油品', '额外第四项'].map((label, index) => ({ field: String(index), label, reason: '可以保留未知', category: 'context', affected_capabilities: [] })),
  capabilities: { road_comparison: { label: '道路比较', status: 'ready', data_state: 'ready', runtime_state: 'not_checked', assessment_scope: 'input_data_only', blockers: [], next_actions: [] } },
}

describe('分组案件档案与资料状态', () => {
  it('无效标签退回概览，只挂载当前分组', () => {
    expect(caseDossierView(null)).toBe('overview')
    expect(caseDossierView('constructor')).toBe('overview')
    expect(caseDossierView('sources')).toBe('sources')
    expect(renderToStaticMarkup(<CaseDossierPanel active="overview" view="materials">材料读取</CaseDossierPanel>)).toBe('')
  })
  it('最多显示三项缺口，不将旧总分、资料就绪解释为案件办结或运行可用', () => {
    const html = renderToStaticMarkup(<CaseQualityStatus quality={qualityFixture} />)
    expect(html).not.toContain('66'); expect(html).not.toContain('额外第四项')
    expect(html).toContain('资料就绪'); expect(html).toContain('运行状态另行检查'); expect(html).toContain('不代表案件办结')
    expect(renderToStaticMarkup(<CaseQualityStatus quality={{ ...qualityFixture, validation: undefined }} />)).toContain('不以历史分数表示完整性')
  })
})
