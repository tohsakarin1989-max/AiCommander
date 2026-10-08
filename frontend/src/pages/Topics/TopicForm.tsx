import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { TopicCondition, TopicDefinition, TopicFilters, TopicOptions, TopicSourceContext, TopicWindow } from '../../services/analysisTopics'
import { categoryNames, kindNames } from './topicPresentation'
import { contextQuestionKind, topicPresets } from './topicPresets'

const localInput = (value?: string) => {
  if (!value) return ''
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 19) : ''
}
export function TopicForm({ pending, onCreate, initial, sourceContext }: {
  pending: boolean; onCreate: (title: string, filters: TopicFilters, options: TopicOptions) => void
  initial?: TopicDefinition; sourceContext?: TopicSourceContext
}) {
  const [title, setTitle] = useState(initial?.question || initial?.title || '')
  const [keyword, setKeyword] = useState(initial?.filters.keyword || '')
  const [start, setStart] = useState(localInput(initial?.filters.start_date))
  const [end, setEnd] = useState(localInput(initial?.filters.end_date))
  const [window, setWindow] = useState<TopicWindow>(initial?.window || { mode: 'fixed' })
  const [conditions, setConditions] = useState<TopicCondition[]>(initial?.filters.conditions || [])
  const [error, setError] = useState('')
  const questionKind = initial?.question_kind || contextQuestionKind(sourceContext)
  const invalidRange = window.mode === 'fixed' && Boolean(start && end && start >= end)
  function change(index: number, value: Partial<TopicCondition>) {
    setConditions(items => items.map((item, i) => i === index ? { ...item, ...value } : item))
  }
  return <form className="topic-form" onSubmit={event => {
    event.preventDefault()
    if (!title.trim() || invalidRange || pending) return
    if (window.mode === 'rolling' && (!Number.isInteger(window.days) || window.days! < 1 || window.days! > 366)) { setError('滚动天数必须为 1 至 366 的整数。'); return }
    const filters: TopicFilters = { ...initial?.filters, keyword: keyword.trim() || undefined,
      start_date: window.mode === 'fixed' && start ? new Date(start).toISOString() : undefined,
      end_date: window.mode === 'fixed' && end ? new Date(end).toISOString() : undefined,
      conditions: conditions.map(item => ({ ...item, value: item.value?.trim() || null })) }
    setError(''); onCreate(title.trim(), filters, { question: title.trim(), question_kind: questionKind, window, ...(sourceContext ? { source_context: sourceContext } : {}) })
  }}>
    {!initial && <fieldset><legend>从常用关注开始</legend><div className="topic-actions">
      {topicPresets.map(preset => <div key={preset.kind}>
        {preset.kind === questionKind ? <button type="button" className="btn-ghost" disabled={pending}
          onClick={() => { setTitle(preset.title); setWindow({ ...preset.window }); setError('') }}>{preset.title}</button>
          : <Link to={preset.entry}>{preset.title}（从{preset.kind === 'case_gaps' ? '案件' : preset.kind === 'facility_context' ? '设施' : '无对象专题'}进入）</Link>}
        <p>{preset.description}</p>
      </div>)}
    </div><p>预设只填写已有的关注类型和时间窗口，下面已填写的条件会保留；保存前可调整。</p></fieldset>}
    <label>想持续关注什么<input value={title} required maxLength={120} placeholder="例如：近期管线案件的手法与资料缺口有什么变化" disabled={pending} onChange={e => setTitle(e.target.value)} /></label>
    {sourceContext && <p>已带入{sourceContext.kind === 'case' ? '案件' : sourceContext.kind === 'facility' ? '设施' : '查询'} #{sourceContext.id}，由服务器核对范围，不需重新选案。</p>}
    {!sourceContext && <p>范围为全部授权案件，以下条件只会收窄范围，不需要逐案选择。</p>}
    <p>关注内容：{sourceContext?.kind === 'case' || initial?.question_kind === 'case_gaps' ? '该案件的资料缺口、已有过程与成果'
      : sourceContext?.kind === 'facility' || initial?.question_kind === 'facility_context' ? '该设施的已有资料与明确关联' : '所选范围的案件条件分布与变化'}。</p>
    <p>关注问题作为名称和说明，实际分析以所选业务范围和条件为准；不会把任意文字问题假装成已完成的自由推理。</p>
    <label>案件关键词（可不填）<input value={keyword} maxLength={100} disabled={pending} onChange={e => setKeyword(e.target.value)} /></label>
    <label>时间窗口<select value={window.mode} disabled={pending} onChange={e => setWindow(e.target.value === 'rolling' ? { mode: 'rolling', days: 30, anchor_hour: 0 } : { mode: 'fixed' })}>
      <option value="fixed">固定范围，重复查看同一时段</option><option value="rolling">滚动范围，持续查看最近一段时间</option></select></label>
    {window.mode === 'rolling' ? <label>最近多少天<input type="number" min={1} max={366} value={window.days || ''} disabled={pending} onChange={e => setWindow(old => ({ ...old, days: Number(e.target.value) }))} /></label> : <>
    <div className="topic-actions">
      <label>案发起始时间（含）<input type="datetime-local" step="1" value={start} disabled={pending} onChange={e => setStart(e.target.value)} /></label>
      <label>案发结束时间（不含）<input type="datetime-local" step="1" value={end} disabled={pending} onChange={e => setEnd(e.target.value)} /></label>
    </div>
    {invalidRange && <p role="alert">结束时间必须晚于起始时间。</p>}
    </>}
    <p>每次任务固定统计截止，续跑时不漂移；不确定发生时间会保留缺口，不编造精确时刻。</p>
    <details><summary>进一步限定手法、油品或表述（可选）</summary>
    <p>下列条件必须同时满足，不需要逐案选择；无条件时统计所选范围的画像质量与表述分布。</p>
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
      onClick={() => setConditions(items => [...items, { category: 'method', kind: 'stated', value: '' }])}>增加条件</button></div>
    </details>
    {error && <p role="alert">{error}</p>}
    <button type="submit" className="btn-primary" disabled={pending || !title.trim() || (window.mode === 'fixed' && invalidRange)}>{pending ? '正在保存' : initial ? '保存条件新版本' : '保存并持续关注'}</button>
  </form>
}
