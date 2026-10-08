import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import CaseAnalysisApplicability, { type AnalysisApplicability } from './CaseAnalysisApplicability'

const fixture: AnalysisApplicability = { version: '8.0-1', boundary: '不改变原始事实', entries: [
  { kind: 'base', status: 'applicable', reason: '已有简要经过', evidence_refs: [] },
  { kind: 'source_inference', status: 'not_applicable', reason: '只有查获地点，不推定盗取来源', evidence_refs: [] },
  { kind: 'road_analysis', status: 'insufficient_data', reason: '道路端点尚不明确', evidence_refs: [] },
] }
describe('分析适用情况展示', () => {
  it('不适用与资料不足分别显示，不当作失败或办结进度', () => {
    const html = renderToStaticMarkup(<CaseAnalysisApplicability value={fixture} />)
    expect(html).toContain('资料可支持'); expect(html).toContain('本次不适用'); expect(html).toContain('现有资料不足')
    expect(html).toContain('不代表本单位处置进展'); expect(html).not.toContain('分析失败')
  })
  it('读取失败和更新中不显示旧适用结果', () => {
    expect(renderToStaticMarkup(<CaseAnalysisApplicability value={fixture} error />)).not.toContain('已有简要经过')
    expect(renderToStaticMarkup(<CaseAnalysisApplicability value={fixture} updating />)).toContain('未用旧版结果')
    expect(renderToStaticMarkup(<CaseAnalysisApplicability />)).toContain('尚无适用性记录')
  })
})
