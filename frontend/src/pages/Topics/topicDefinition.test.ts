import { describe, expect, it } from 'vitest'
import { definitionLines } from './topicPresentation'

describe('实际条件修订契约', () => {
  it('解包definition中的问题与窗口，不使用当前条件替换历史', () => {
    const lines = definitionLines({ revision: 2, created_at: '2026-09-30', definition: {
      revision: 2, title: '旧名称', question: '历史原油条件怎样变化', filters: { oil_types: ['原油'] },
      window: { mode: 'rolling', days: 30, anchor_hour: 8 },
    } })
    expect(lines).toContain('第 2 版：历史原油条件怎样变化')
    expect(lines).toContain('滚动窗口：30 天，北京时间每日 8 时为锚点')
    expect(lines).toContain('油品字段：原油')
  })
  it('固定窗口的无附加条件明确标注授权范围', () => {
    expect(definitionLines({ revision: 1, created_at: '', definition: { revision: 1, title: '范围统计',
      question: '', filters: {}, window: { mode: 'fixed' } } })).toEqual([
      '第 1 版：范围统计', '固定时间窗口', '全部授权案件，未增加其他条件',
    ])
  })
})
