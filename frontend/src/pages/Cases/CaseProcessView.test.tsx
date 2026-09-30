import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CaseProcessView from './CaseProcessView'
import type { CaseProcess, ProcessTextReference } from '../../services/caseProcess'

const reference: ProcessTextReference = { kind: 'text', field: 'description', source_sha256: 'a'.repeat(64),
  start: 0, end: 5, quote: '未转运原油', source_revision_id: 12, snapshot_path: ['case', 'description'] }
const fixture = (): CaseProcess => ({ version: 'case-process-6.3-1', source_revision_id: 12, source_hash: 'b'.repeat(64),
  events: [{ id: 'event', statement_kind: 'negated', judgment_status: 'rule_candidate', reference,
    relation_status: 'sentence_cooccurrence_only', missing_dimensions: ['upstream', 'time'],
    actions: [{ value: '转运', kind: 'negated', reference, is_official_fact: false }],
    objects: [], locations: [], measurements: [], time_intervals: [], is_official_fact: false }],
  relations: [], conflicts: [], gaps: [], structured_context: { locations: [], measurements: [] },
  coverage: { state: 'rule_scan_complete', limit: 100, omitted_fragments: 0 }, boundary: '原文候选，不是核实事实' })

describe('版本化案件过程', () => {
  it('过程出处和未知保持可见，不新增必填操作或事实认定', () => {
    const html = renderToStaticMarkup(<CaseProcessView process={fixture()} />)
    for (const value of ['已交代的环节', '转运（原文否定）', '来源版本：12', '未转运原油', '不新增必填操作', '不代表记录已完全一致']) expect(html).toContain(value)
    expect(html).not.toContain('当前仅有部分')
  })
  it('冲突双方保留原文，部分结果不冒充完整过程', () => {
    const input = fixture()
    input.coverage.state = 'partial'
    input.conflicts = [{ id: 'conflict', category: 'action', value: '转运', event_ids: ['event'],
      references: [reference, { ...reference, start: 8, end: 12, quote: '转运原油' }], status: 'needs_context_review' }]
    const html = renderToStaticMarkup(<CaseProcessView process={input} />)
    for (const value of ['当前仅有部分', '未转运原油', '转运原油', '不自动选择']) expect(html).toContain(value)
  })
  it('时间保留小时或分钟精度，不因标准化补零而升级精度', () => {
    const input = fixture()
    input.events[0].time_intervals = [{ start: '2026-09-20T23:00', end: '2026-09-21T01:30',
      start_precision: 'hour', end_precision: 'minute', timezone: null, reference }]
    const html = renderToStaticMarkup(<CaseProcessView process={input} />)
    for (const value of ['23:00（小时精度）', '01:30（分钟精度', '时区未注明', '不自动作为已确认发生时间']) expect(html).toContain(value)
  })
})
