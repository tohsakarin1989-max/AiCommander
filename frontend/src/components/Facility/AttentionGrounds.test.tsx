import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { AttentionItem } from '../../types/attention'
import AttentionGrounds, { AttentionItemContent } from './AttentionGrounds'

const item: AttentionItem = { object_key: 'asset:1', object_type: 'facility', object_id: 1, label: '合成井',
  state: 'new_information', support_record_count: 1, evidence_refs: ['case:3'], gaps: [], boundary: '关注不等于涉案。',
  layers: { spatial_proximity: { state: 'ready', record_count: 1, raw_record_count: 2, gaps: [], boundary: '只表示直线邻近。',
    items: [{ case_ids: [3, 4], distance_km: 0.5, evidence_refs: ['case:3'] }] },
  production_background: { state: 'restricted', gaps: [], boundary: '限制', items: [{ label: '不该展示的台账' }] } } }

describe('分层关注依据', () => {
  it('单条不称规律、空间不作涉案、受限不泄露内容数量', () => {
    const html = renderToStaticMarkup(<MemoryRouter><AttentionItemContent item={item} /></MemoryRouter>)
    expect(html).toContain('单条新增情况，不称为规律'); expect(html).toContain('非道路距离')
    expect(html).toContain('资料受限，不展示内容与数量'); expect(html).not.toContain('不该展示的台账')
    expect(html).toContain('1 起独立来源记录'); expect(html).toContain('/cases?caseId=3')
  })
  it('空和部分结果不冒充无事发生或完整全集', () => {
    const html = renderToStaticMarkup(<AttentionGrounds value={{ version: 'test', items: [], boundary: '不形成风险分',
      coverage: { cases_scanned: 2, selection: 'complete_authorized_window', complete: false } }} />)
    expect(html).toContain('不代表完整范围'); expect(html).toContain('不为凑数量生成建议')
  })
})
