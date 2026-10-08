import { describe, expect, it, vi } from 'vitest'
import { dismissInBatches, exactReference, IncompleteDismissal } from './topicChangeDismissal'
import type { TopicChangeReference } from '../../services/analysisTopics'

const refs = (n: number): TopicChangeReference[] => Array.from({ length: n }, (_, i) => ({
  topic_id: `topic-${i}`, snapshot_id: `snapshot-${i}`, revision: 2, content_sha256: 'a'.repeat(64),
}))
const receipt = async (sources: TopicChangeReference[]) => ({ sources, dismissed: sources.length })

describe('精确版本提示分批关闭', () => {
  it('超过100个来源也完整保留，全部确认才成功', async () => {
    const send = vi.fn(receipt)
    await dismissInBatches(refs(205), send)
    expect(send.mock.calls.map(([batch]) => batch.length)).toEqual([100, 100, 5])
    expect(send.mock.calls.flatMap(([batch]) => batch)).toEqual(refs(205))
  })
  it('中途失败保留不确定批次，重试只使用未确认的原版本', async () => {
    const send = vi.fn(receipt).mockImplementationOnce(receipt).mockRejectedValueOnce(new Error('lost response'))
    let failure: IncompleteDismissal | undefined
    try { await dismissInBatches(refs(205), send) } catch (error) { failure = error as IncompleteDismissal }
    expect(failure).toBeInstanceOf(IncompleteDismissal)
    expect(failure?.remaining).toEqual(refs(205).slice(100))
    const retry = vi.fn(receipt)
    await dismissInBatches(failure!.remaining, retry)
    expect(retry.mock.calls[0][0]).toEqual(send.mock.calls[1][0])
    expect(retry.mock.calls.map(([batch]) => batch.length)).toEqual([100, 5])
  })
  it('错误回执不当成功，用户切换后不发送下一批', async () => {
    const mismatch = vi.fn(async (sources: TopicChangeReference[]) => ({ sources: [], dismissed: sources.length }))
    await expect(dismissInBatches(refs(1), mismatch)).rejects.toMatchObject({ remaining: refs(1) })
    let active = true
    const send = vi.fn(async (sources: TopicChangeReference[]) => { active = false; return receipt(sources) })
    await expect(dismissInBatches(refs(101), send, () => active)).rejects.toMatchObject({ remaining: refs(101).slice(100) })
    expect(send).toHaveBeenCalledTimes(1)
  })
  it('标题和链接不进入严格请求契约', () => {
    expect(exactReference({ ...refs(1)[0], title: '标题', target_path: '/topics' } as TopicChangeReference)).toEqual(refs(1)[0])
  })
})
