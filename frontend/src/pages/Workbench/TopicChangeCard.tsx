import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { analysisTopicsApi, type TopicChangeReference } from '../../services/analysisTopics'
import type { DailyTopicChange } from '../../services/workbench'
import { dismissInBatches, exactReference, IncompleteDismissal } from './topicChangeDismissal'

export default function TopicChangeCard({ change, onDismissed }: {
  change: DailyTopicChange; onDismissed: () => void
}) {
  const [pending, setPending] = useState(false)
  const [remaining, setRemaining] = useState<TopicChangeReference[] | null>(null)
  const [notice, setNotice] = useState('')
  const live = useRef(true)
  const submitting = useRef(false)
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  async function dismiss() {
    if (submitting.current) return
    const sources = remaining ?? change.sources?.map(exactReference) ?? []
    if (!sources.length) return
    submitting.current = true; setPending(true); setNotice('')
    try {
      await dismissInBatches(sources, analysisTopicsApi.dismissChanges, () => live.current)
      if (live.current) { setRemaining(null); setNotice('本条已不显示；以后新变化仍会提示。'); onDismissed() }
    } catch (error) {
      if (live.current) {
        setRemaining(error instanceof IncompleteDismissal ? error.remaining : sources)
        setNotice('尚未全部确认，未确认的原版本已保留。可继续处理；权限变化时请重新读取。')
      }
    } finally { submitting.current = false; if (live.current) setPending(false) }
  }
  return <li>
    <h3><Link to={change.target_path}>{change.title}</Link></h3>
    {change.object && <p>{change.object.kind === 'case' ? '案件' : '设施'} #{change.object.id} 的同对象变化已合并。</p>}
    <p>{change.summary}</p>
    <ul>{change.items.map((item, index) => <li key={`${item.code}:${index}`}>{item.message}</li>)}</ul>
    {!!change.sources?.length && <>
      <details><summary>来源专题版本（{change.sources.length}）</summary><ul>{change.sources.map(source =>
        <li key={source.snapshot_id}><Link to={source.target_path}>{source.title} · 第 {source.revision} 版</Link></li>)}</ul></details>
      <button className="btn-ghost" disabled={pending} onClick={() => void dismiss()}>{pending ? '正在确认' : remaining ? '继续处理未确认提示' : '本次变化不再提示'}</button>
      <p>仅关闭这次提示，不暂停专题、不删除成果，也不代表业务已处理。</p>
    </>}
    {notice && <p role="status">{notice}</p>}
  </li>
}
