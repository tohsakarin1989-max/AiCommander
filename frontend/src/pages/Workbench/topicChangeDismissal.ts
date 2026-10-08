import type { TopicChangeReference } from '../../services/analysisTopics'

export class IncompleteDismissal extends Error {
  constructor(public readonly remaining: TopicChangeReference[]) {
    super('部分请求尚未确认，保留原版本继续处理')
  }
}

export const exactReference = (source: TopicChangeReference): TopicChangeReference => ({
  topic_id: source.topic_id, snapshot_id: source.snapshot_id,
  revision: source.revision, content_sha256: source.content_sha256,
})

export async function dismissInBatches(
  sources: TopicChangeReference[],
  send: (batch: TopicChangeReference[]) => Promise<{ sources: TopicChangeReference[]; dismissed: number }>,
  isCurrent: () => boolean = () => true,
): Promise<void> {
  let remaining = sources.map(exactReference)
  while (remaining.length) {
    if (!isCurrent()) throw new IncompleteDismissal(remaining)
    const batch = remaining.slice(0, 100)
    try {
      const response = await send(batch)
      // An uncertain receipt is not success; retry the identical exact versions.
      if (response.dismissed !== batch.length || JSON.stringify(response.sources.map(exactReference)) !== JSON.stringify(batch)) throw new Error('receipt_mismatch')
    } catch { throw new IncompleteDismissal(remaining) }
    remaining = remaining.slice(batch.length)
  }
}
