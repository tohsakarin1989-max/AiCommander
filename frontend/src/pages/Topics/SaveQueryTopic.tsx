import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { analysisTopicsApi } from '../../services/analysisTopics'
import { topicError } from './topicPresentation'

export function SaveQueryTopic({ queryId, question }: { queryId: string; question: string }) {
  const [title, setTitle] = useState(question.slice(0, 120))
  const navigate = useNavigate()
  const live = useRef(true)
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  const save = useMutation({ mutationFn: () => analysisTopicsApi.fromQuery(queryId, title.trim()),
    onSuccess: topic => { if (live.current) navigate(`/topics?topic=${topic.id}`) } })
  return <details><summary>保存为持续专题</summary>
    <p>保存本次有效筛选条件，不把模型回答当作事实。专题后台复用案件画像；相似度或道路专用条件无法等价保存时会明确拒绝。</p>
    <form className="query-form" onSubmit={e => { e.preventDefault(); if (title.trim() && !save.isPending) save.mutate() }}>
      <label>专题名称<input value={title} required maxLength={120} disabled={save.isPending} onChange={e => setTitle(e.target.value)} /></label>
      <button className="btn-ghost" type="submit" disabled={save.isPending || !title.trim()}>{save.isPending ? '正在保存' : '保存并打开专题'}</button>
      {save.error && <p role="alert">{topicError(save.error)}</p>}
    </form>
  </details>
}
