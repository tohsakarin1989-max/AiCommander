import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { QueryResult } from './QueryResult'

const hypothesis = { id: 'h', title: '待核查区域', claim: '候选解释', rule_support: 60,
  supporting_evidence: ['支持内容'], counter_evidence: ['反向内容'], information_gaps: ['缺口内容'],
  evidence_refs: ['case:1'], boundary: '不是正式事实' }
function render(item: Record<string, unknown>) {
  return renderToStaticMarkup(<QueryResult card={{ tool: 'summarize_results', state: 'ready',
    data: { total: 1, items: [{ run_id: 'r', ...item }] } }} />)
}

describe('existing insight result presentation', () => {
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
