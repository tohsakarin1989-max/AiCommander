import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { intelligentQueriesApi, queryEntryContext } from '../../services/intelligentQueries'
import type { InitialQueryContext } from '../../services/intelligentQueries'
import { activeQuery, canFollowup, conditionLines, conditionNames, conditionValue, failureText, queryIdValid, requestFailure, statusNames, toolNames } from './queryPresentation'
import { QueryResult } from './QueryResult'
import './IntelligentQuery.css'

const examples = ['查找包含“管线”的案件', '统计当前授权范围的案件数量', '查找“大庆”相关地点和设施', '汇总已有研判成果']

export default function Assistant() {
  const { user, sessionEpoch } = useAuth()
  const [params, setParams] = useSearchParams()
  const runId = params.get('query') || ''
  const entry = queryEntryContext(params)
  const entryConditions = entry.initialContext ? conditionLines({
    case_filters: { ...entry.initialContext.filters,
      ...(entry.initialContext.source_case_id ? { case_id: entry.initialContext.source_case_id } : {}) },
    area: entry.initialContext.filters.operational_area_id ?? null, tool_defaults: {},
  }) : []
  const [question, setQuestion] = useState('')
  const [exportState, setExportState] = useState('')
  const exportAbort = useRef<AbortController | null>(null)
  useEffect(() => {
    setExportState('')
    return () => { exportAbort.current?.abort(); exportAbort.current = null }
  }, [runId, sessionEpoch])
  const live = useRef(true)
  const selection = useRef(runId)
  selection.current = runId
  const createSource = `${user?.id}:${sessionEpoch}:${params.toString()}`
  const createSelection = useRef(createSource)
  createSelection.current = createSource
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  const key = ['intelligent-query', user?.id, sessionEpoch, runId]
  const task = useQuery({
    queryKey: key, queryFn: ({ signal }) => intelligentQueriesApi.read(runId, signal),
    enabled: queryIdValid(runId), retry: false,
    refetchInterval: query => !query.state.error && activeQuery(query.state.data?.status) ? 1500 : false,
  })
  const create = useMutation({
    mutationFn: ({ text, parentId, initialContext }: {
      text: string; sourceId: string; parentId?: string; initialContext?: InitialQueryContext
    }) => intelligentQueriesApi.create(text, parentId, initialContext),
    onSuccess: (data, variables) => {
      if (!live.current || createSelection.current !== variables.sourceId) return
      setQuestion('')
      setParams({ query: data.id })
    },
  })
  const cancel = useMutation({
    mutationFn: intelligentQueriesApi.cancel,
    onSuccess: (_result, id) => {
      if (!live.current || selection.current !== id) return
      // Cancellation is allowed after scope revocation; it grants no read access.
      void task.refetch()
    },
  })
  const current = !task.error && task.data?.id === runId ? task.data : undefined
  const busy = create.isPending || activeQuery(current?.status)
  const canQuery = user?.role === 'admin' || user?.role === 'analyst'
  const followup = canFollowup(current)
  const conditions = conditionLines(current?.result.query_conditions ?? current?.followup_context?.conditions ?? current?.initial_context?.conditions)
  const sourceCase = current?.initial_context?.source_case ?? current?.followup_context?.source_case
  async function download(format: 'docx' | 'pdf') {
    if (!current || !followup || exportAbort.current) return
    const id = current.id
    const controller = new AbortController()
    exportAbort.current = controller
    setExportState('正在生成报告…')
    try {
      const blob = await intelligentQueriesApi.document(id, format, controller.signal)
      if (!live.current || selection.current !== id || controller.signal.aborted) return
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url; link.download = `专题查询-${id}.${format}`
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      setExportState('报告已生成，使用本次查询的历史证据。')
    } catch {
      if (!controller.signal.aborted && live.current && selection.current === id)
        setExportState('导出未完成，请刷新查询确认权限或联系管理员检查文档服务。')
    } finally {
      if (exportAbort.current === controller) exportAbort.current = null
    }
  }
  function submit() {
    if (!canQuery || busy || !question.trim() || entry.error || (runId && !current)) return
    cancel.reset()
    create.mutate({ text: question.trim(), sourceId: createSource, parentId: followup ? runId : undefined,
      initialContext: !runId ? entry.initialContext : undefined })
  }
  return <main className="page-scrollable intelligent-query">
    <header className="page-title"><h1>智能助手</h1><span className="sub">案件与地图查询</span></header>
    <p className="query-intro">输入要查的问题。系统在当前授权范围内调用只读工具，结果不自动变成案件结论或执行任务。</p>
    {!!entryConditions.length && <section className="query-history-note" aria-label="带入的案件与筛选条件">
      <strong>已带入当前案件与筛选条件</strong><ul>{entryConditions.map(line => <li key={line}>{line}</li>)}</ul>
      <p>这些条件只限定查询，不授予数据权限；提交时将核对当前案件及版本。未提交前不会运行分析。</p>
    </section>}
    {entry.error && <p role="alert">{entry.error}</p>}
    <form onSubmit={event => { event.preventDefault(); submit() }} className="query-form">
      <label htmlFor="query-question">{followup ? '继续追问' : '查询问题'}</label>
      {followup && <p className="query-history-note">将继承当前查询条件。改变条件请在问题中说明；不继承时选择“新查询”。</p>}
      <textarea id="query-question" value={question} onChange={event => setQuestion(event.target.value)}
        maxLength={2000} rows={3} placeholder="例如：比较 2026年8月 与上一个等长周期的盗油案件数量。"
        disabled={!canQuery || create.isPending} />
      <div className="query-actions"><button className="btn-primary" type="submit" disabled={!canQuery || busy || !question.trim() || Boolean(entry.error) || Boolean(runId && !current)}>
        {create.isPending ? '正在提交' : followup ? '继续追问' : '提交查询'}</button>
        {activeQuery(current?.status) && <button className="btn-ghost" type="button" disabled={cancel.isPending}
          onClick={() => cancel.mutate(runId)}>{cancel.isPending ? '正在取消' : '取消本次查询'}</button>}
        {(runId || entry.initialContext || entry.error) && <button className="btn-ghost" type="button" disabled={busy} onClick={() => {
          setParams({}); create.reset(); cancel.reset()
        }}>新查询</button>}
      </div>
      {!canQuery && <p role="status">当前账号不能发起智能查询，可继续使用案件和地图浏览。</p>}
    </form>
    {!runId && <div className="query-examples" aria-label="问题示例">{examples.map(example =>
      <button type="button" className="btn-ghost" key={example} disabled={!canQuery || create.isPending}
        onClick={() => setQuestion(example)}>{example}</button>)}</div>}
    {create.error && <p role="alert">{requestFailure(create.error, true)}</p>}
    {cancel.error && <p role="alert">取消未得到确认，请刷新任务状态后再试。</p>}
    {runId && !queryIdValid(runId) && <p role="alert">任务编号无效，请发起新查询。</p>}
    {task.isFetching && !current && !task.error && runId && <p role="status">正在读取任务状态…</p>}
    {task.error && <section role="alert"><p>{requestFailure(task.error)}</p>
      <button className="btn-ghost" onClick={() => void task.refetch()}>重新读取</button></section>}
    {current && <section className="query-output">
      <div className="query-status" role="status"><strong>{statusNames[current.status] || '状态未知'}</strong>
        <button className="btn-ghost" disabled={task.isFetching} onClick={() => void task.refetch()}>刷新状态</button></div>
      <p className="query-original">{current.query}</p>
      {sourceCase && <p className="query-history-note">来源案件 ID：{sourceCase.case_id}。此查询绑定提交时的案件版本。</p>}
      {followup && <div className="query-actions">
        <button className="btn-ghost" disabled={exportState === '正在生成报告…'} onClick={() => void download('docx')}>导出 Word</button>
        <button className="btn-ghost" disabled={exportState === '正在生成报告…'} onClick={() => void download('pdf')}>导出 PDF</button>
      </div>}
      {exportState && <p role="status">{exportState}</p>}
      {current.followup_context && <p className="query-history-note">接续：{current.followup_context.previous_question}。
        <button type="button" className="btn-ghost" disabled={busy} onClick={() => setParams({ query: current.followup_context!.parent_query_id })}>查看上一轮</button>
      </p>}
      {!!conditions.length && <section aria-label="当前查询条件"><strong>当前查询条件</strong><ul>
        {conditions.map(line => <li key={line}>{line}</li>)}
      </ul></section>}
      {current.result.trace?.flatMap(step => step.condition_changes ?? []).map((change, index) =>
        <p className="query-history-note" key={index}>条件变化：{conditionNames[change.field] || change.field}，
          {conditionValue(change.previous)} → {conditionValue(change.current)}。依据：“{change.basis}”。</p>)}
      {current.status === 'queued' && <p>任务已保存，等待后台领取。长时间未开始时请联系管理员检查队列。</p>}
      {current.status === 'running' && <p>正在执行只读查询，可取消；后台故障不会影响案件录入。</p>}
      {current.result.error_code && <p role="status">{failureText(current.result.error_code)}</p>}
      {!!current.result.cards?.length && <p className="query-history-note">以下是该次查询的历史结果，数据更新后请重新查询。</p>}
      {current.result.cards?.map((card, index) => <QueryResult key={index} card={card} />)}
      {!!current.result.trace?.length && <details><summary>查看工具轨迹（{current.result.trace.length} 步）</summary>
        <ol>{current.result.trace.map(step => <li key={step.step}>{toolNames[step.tool] || '只读查询'}{step.duration_ms != null ? ` · ${step.duration_ms} 毫秒` : ''}{step.error_code ? ' · 条件未满足，本步未执行' : ''}</li>)}</ol>
      </details>}
    </section>}
  </main>
}
