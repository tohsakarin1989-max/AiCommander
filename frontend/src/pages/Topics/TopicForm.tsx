import { useState } from 'react'
import type { TopicCondition, TopicFilters } from '../../services/analysisTopics'
import { categoryNames, kindNames } from './topicPresentation'

export function TopicForm({ pending, onCreate }: { pending: boolean; onCreate: (title: string, filters: TopicFilters) => void }) {
  const [title, setTitle] = useState('')
  const [keyword, setKeyword] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [conditions, setConditions] = useState<TopicCondition[]>([])
  const invalidRange = Boolean(start && end && start >= end)
  function change(index: number, value: Partial<TopicCondition>) {
    setConditions(items => items.map((item, i) => i === index ? { ...item, ...value } : item))
  }
  return <form className="topic-form" onSubmit={event => {
    event.preventDefault()
    if (!title.trim() || invalidRange || pending) return
    onCreate(title.trim(), { ...(keyword.trim() ? { keyword: keyword.trim() } : {}),
      ...(start ? { start_date: new Date(start).toISOString() } : {}),
      ...(end ? { end_date: new Date(end).toISOString() } : {}),
      conditions: conditions.map(item => ({ ...item, value: item.value?.trim() || null })) })
  }}>
    <label>专题名称<input value={title} required maxLength={120} disabled={pending} onChange={e => setTitle(e.target.value)} /></label>
    <label>案件关键词（可不填）<input value={keyword} maxLength={100} disabled={pending} onChange={e => setKeyword(e.target.value)} /></label>
    <div className="topic-actions">
      <label>案发起始时间（含）<input type="datetime-local" value={start} disabled={pending} onChange={e => setStart(e.target.value)} /></label>
      <label>案发结束时间（不含）<input type="datetime-local" value={end} disabled={pending} onChange={e => setEnd(e.target.value)} /></label>
    </div>
    {invalidRange && <p role="alert">结束时间必须晚于起始时间。</p>}
    <p>默认使用全部授权案件。下列条件必须同时满足，不需要逐案选择；无条件时仍会统计画像质量与表述分布。</p>
    {conditions.map((item, index) => <fieldset key={index} className="topic-condition"><legend>条件 {index + 1}</legend>
      <label>类别<select value={item.category} disabled={pending} onChange={e => change(index, { category: e.target.value })}>
        {Object.entries(categoryNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}
      </select></label>
      <label>标准词项（留空表示本类任一词项）<input value={item.value || ''} maxLength={100} disabled={pending}
        onChange={e => change(index, { value: e.target.value })} /></label>
      <label>表述性质<select value={item.kind} disabled={pending} onChange={e => change(index, { kind: e.target.value })}>
        {Object.entries(kindNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}
      </select></label>
      <button type="button" className="btn-ghost" disabled={pending} onClick={() => setConditions(items => items.filter((_, i) => i !== index))}>移除条件 {index + 1}</button>
    </fieldset>)}
    <div className="topic-actions"><button type="button" className="btn-ghost" disabled={pending || conditions.length >= 8}
      onClick={() => setConditions(items => [...items, { category: 'method', kind: 'stated', value: '' }])}>增加条件</button>
      <button type="submit" className="btn-primary" disabled={pending || !title.trim() || invalidRange}>{pending ? '正在保存' : '保存并生成专题'}</button></div>
  </form>
}
