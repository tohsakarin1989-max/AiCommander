import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import TopicChangeCard from './TopicChangeCard'
import type { DailyTopicChange } from '../../services/workbench'
import { analysisTopicsApi } from '../../services/analysisTopics'

vi.mock('../../services/analysisTopics', () => ({ analysisTopicsApi: { dismissChanges: vi.fn() } }))

describe('同对象提示只读展示', () => {
  it('保留所有来源版本链接，渲染不调用忽略接口', () => {
    const change: DailyTopicChange = { group_key: 'case:8', object: { kind: 'case', id: 8 },
      topic_id: 'topic-1', title: '资料变化', revision: 2, summary: '缺项有变化', items: [], target_path: '/topics?topic=topic-1&revision=2',
      sources: Array.from({ length: 105 }, (_, index) => ({ topic_id: `topic-${index}`, snapshot_id: `snapshot-${index}`,
        revision: 2, content_sha256: 'a'.repeat(64), title: `关注${index}`, target_path: `/topics?topic=topic-${index}&revision=2` })) }
    const html = renderToStaticMarkup(<MemoryRouter><TopicChangeCard change={change} onDismissed={vi.fn()} /></MemoryRouter>)
    expect(html).toContain('案件 #8 的同对象变化已合并')
    expect(html).toContain('来源专题版本（105）')
    expect(html).toContain('topic-104&amp;revision=2')
    expect(html).toContain('本次变化不再提示')
    expect(html).toContain('不代表业务已处理')
    expect(analysisTopicsApi.dismissChanges).not.toHaveBeenCalled()
  })
})
