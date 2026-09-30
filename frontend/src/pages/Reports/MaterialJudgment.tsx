import { useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { materialRequestKey, resultKinds, resultPath, resultsApi } from '../../services/results'
import type { JudgmentDecision, ResultMaterial, ResultSource } from '../../services/results'

export const judgmentLabels: Record<JudgmentDecision, string> = {
  confirm: '确认本版材料', retain_reference: '保留参考', insufficient_evidence: '证据不足', exclude_with_evidence: '有依据排除',
}
export default function MaterialJudgment({ material, identity, allowed, onSaved }: { material: ResultMaterial; identity: string; allowed: boolean; onSaved: () => void }) {
  const [open, setOpen] = useState(false)
  const [decision, setDecision] = useState<JudgmentDecision>('retain_reference')
  const [note, setNote] = useState('')
  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [sources, setSources] = useState<ResultSource[]>([])
  const request = useRef<{ signature: string; key: string } | null>(null)
  const matches = useQuery({ queryKey: ['judgment-source-search', identity, material.kind, material.id, search],
    queryFn: ({ signal }) => resultsApi.list({ q: search, limit: 20 }, signal), enabled: allowed && open && !!search, retry: false, gcTime: 0 })
  const submit = useMutation({ mutationFn: async () => {
    const payload = { decision, note: note.trim(), additional_sources: sources }
    const signature = JSON.stringify(payload)
    if (request.current?.signature !== signature) request.current = { signature, key: materialRequestKey() }
    return resultsApi.judge(material, { ...payload, idempotency_key: request.current.key })
  }, onSuccess: () => { setOpen(false); setNote(''); setSources([]); request.current = null; onSaved() } })
  const isSelected = (item: ResultSource) => sources.some(s => s.kind === item.kind && s.id === item.id)
  return <section className="material-judgment" aria-label="本版人工判断">
    <h2>人工判断 <small>按需记录，不是必经流程</small></h2>
    <p>决定只绑定这份内容版本，不自动变成案件事实、办理状态或执行任务。</p>
    <ul>{material.judgments?.map(item => <li key={item.id}>
      <strong>{judgmentLabels[item.decision] || '历史决定'}</strong> · {item.created_at} · 记录人 #{item.created_by}
      <p>{item.note}</p><ul>{item.additional_sources?.map(source => <li key={`${source.kind}:${source.id}`}><Link to={resultPath(source.kind, source.id)}>{resultKinds[source.kind]} #{source.id}</Link></li>)}</ul>
    </li>)}</ul>
    {!material.judgments?.length && <p>尚无本版判断；不影响查看和导出。</p>}
    {allowed && <button className="btn-ghost" onClick={() => setOpen(value => !value)}>{open ? '收起判断' : '按需记录判断'}</button>}
    {open && <form className="material-judgment-form" onSubmit={event => { event.preventDefault(); if (note.trim()) submit.mutate() }}>
      <label>决定<select value={decision} disabled={submit.isPending} onChange={e => setDecision(e.target.value as JudgmentDecision)}>{Object.entries(judgmentLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>
      <label>理由<textarea required maxLength={4000} rows={3} value={note} disabled={submit.isPending} onChange={e => setNote(e.target.value)} /></label>
      <fieldset disabled={submit.isPending}><legend>补充依据（可选；有依据排除时必选）</legend>
        <label>查找已保存材料<input value={keyword} maxLength={100} onChange={e => setKeyword(e.target.value)} /></label>
        <button className="btn-ghost" type="button" disabled={!keyword.trim()} onClick={() => setSearch(keyword.trim())}>检索依据</button>
        {matches.error ? <p role="alert">依据目录暂不可读，未展示缓存内容。</p> : matches.isFetching ? <p role="status">正在检索…</p> : <ul>{matches.data?.items.filter(item => !(item.kind === material.kind && item.id === material.id)).map(item => <li key={`${item.kind}:${item.id}`}>
          <label><input type="checkbox" checked={isSelected(item)} disabled={!isSelected(item) && sources.length >= 10} onChange={e => setSources(previous => e.target.checked ? [...previous, { kind: item.kind, id: item.id, content_sha256: item.content_sha256 }] : previous.filter(s => s.kind !== item.kind || s.id !== item.id))} />{resultKinds[item.kind]} · {item.title}</label>
        </li>)}</ul>}
        <ul>{sources.map(item => <li key={`${item.kind}:${item.id}`}>{resultKinds[item.kind]} #{item.id} <button className="btn-ghost" type="button" onClick={() => setSources(items => items.filter(s => s !== item))}>移除</button></li>)}</ul>
      </fieldset>
      {submit.error && <p role="alert">判断未保存。请核对材料权限与版本；相同内容可重试，不会重复记录。</p>}
      <button className="btn-primary" disabled={submit.isPending || !note.trim() || decision === 'exclude_with_evidence' && !sources.length}>{submit.isPending ? '正在保存' : '保存本版判断'}</button>
    </form>}
  </section>
}
