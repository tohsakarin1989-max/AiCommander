import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { analysisTopicsApi as api } from '../../services/analysisTopics'
import type { TopicFilters } from '../../services/analysisTopics'
import { ProfileAggregateContent } from '../Assistant/ProfileAggregateContent'
import { queryIdValid, rowsOf } from '../Assistant/queryPresentation'
import { TopicForm } from './TopicForm'
import { TopicLinkedViews } from './TopicViews'
import { categoryNames, filterLines, kindNames, topicError, topicState } from './topicPresentation'
import './Topics.css'

const tabs = { overview: '总体与变化', groups: '条件案组', map: '地图与时间线', materials: '已有成果与周期材料' }
const revisionValue = (value: string | null) => value && /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : undefined

export default function Topics() {
  const { user, sessionEpoch } = useAuth()
  return <TopicWorkspace key={`${user?.id}:${sessionEpoch}`} allowed={user?.role === 'admin' || user?.role === 'analyst'}
    identity={`${user?.id}:${sessionEpoch}`} />
}

function TopicWorkspace({ allowed, identity }: { allowed: boolean; identity: string }) {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const id = params.get('topic') || ''
  const revision = revisionValue(params.get('revision'))
  const invalid = Boolean(id && !queryIdValid(id) || params.has('revision') && !revision)
  const [listPage, setListPage] = useState(1)
  const [page, setPage] = useState(1)
  const [historyPage, setHistoryPage] = useState(1)
  const [tab, setTab] = useState<keyof typeof tabs>('overview')
  const [showForm, setShowForm] = useState(false)
  const [question, setQuestion] = useState('')
  const [notes, setNotes] = useState('')
  const [evidenceId, setEvidenceId] = useState<number | null>(null)
  const [notice, setNotice] = useState('')
  const [exporting, setExporting] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const currentSelection = `${identity}:${id}:${revision ?? 'latest'}`
  const selection = useRef(currentSelection)
  selection.current = currentSelection
  const live = useRef(true)
  useEffect(() => { live.current = true; return () => { live.current = false; abort.current?.abort() } }, [])
  useEffect(() => {
    setPage(1); setHistoryPage(1); setEvidenceId(null); setNotice(''); setQuestion(''); setExporting(false)
    abort.current?.abort(); abort.current = null
  }, [id, revision])
  const list = useQuery({ queryKey: ['analysis-topics', identity, listPage],
    queryFn: ({ signal }) => api.list(listPage, signal), enabled: allowed, retry: false })
  const detail = useQuery({ queryKey: ['analysis-topic', identity, id, revision, page],
    queryFn: ({ signal }) => api.read(id, revision, page, signal), enabled: allowed && !!id && !invalid,
    retry: false, refetchInterval: query => !query.state.error && ['queued', 'running'].includes(query.state.data?.refresh_state || '') ? 2500 : false })
  const topic = !detail.error && detail.data?.id === id ? detail.data : undefined
  const snapshot = topic?.snapshot
  useEffect(() => { setNotes(topic?.notes || '') }, [topic?.id, topic?.notes])
  // Once available, pin every tab and export to the same explicit revision.
  useEffect(() => {
    if (snapshot && !revision && !detail.isFetching) setParams({ topic: id, revision: String(snapshot.revision) }, { replace: true })
  }, [snapshot?.revision, id, revision, detail.isFetching, setParams])
  const view = useQuery({ queryKey: ['topic-views', identity, id, snapshot?.id, page],
    queryFn: ({ signal }) => api.views(id, snapshot!.revision, page, signal),
    enabled: !!snapshot && tab !== 'overview', retry: false })
  const history = useQuery({ queryKey: ['topic-history', identity, id, snapshot?.id, historyPage],
    queryFn: ({ signal }) => api.history(id, historyPage, signal), enabled: !!topic && !!snapshot, retry: false })
  const evidence = useQuery({ queryKey: ['topic-evidence', identity, id, snapshot?.id, evidenceId],
    queryFn: ({ signal }) => api.evidence(id, snapshot!.revision, evidenceId!, signal),
    enabled: !!snapshot && evidenceId != null, retry: false })
  const create = useMutation({ mutationFn: ({ title, filters }: { title: string; filters: TopicFilters; source: string }) => api.create(title, filters),
    onSuccess: (result, variables) => {
      if (!live.current || selection.current !== variables.source) return
      setShowForm(false); setParams({ topic: result.id }); void list.refetch()
    } })
  const action = useMutation({
    mutationFn: async ({ kind, source }: { kind: 'pause' | 'notes' | 'refresh' | 'question'; source: string }) => {
      if (source !== selection.current || !topic) throw new Error('selection_changed')
      if (kind === 'refresh') return api.refresh(id)
      if (kind === 'question') return api.question(id, snapshot!.revision, question.trim())
      return api.update(id, kind === 'notes' ? { notes } : { paused: !topic.paused })
    },
    onSuccess: (result, variables) => {
      if (!live.current || selection.current !== variables.source) return
      if (variables.kind === 'question') navigate(`/assistant?query=${result.id}`)
      else { setNotice(variables.kind === 'refresh' ? '已请求更新，当前仍显示选定版本。完成后可切换最新成果。' : '设置已保存。'); void detail.refetch(); void list.refetch() }
    },
  })
  function run(kind: 'pause' | 'notes' | 'refresh' | 'question') { setNotice(''); action.mutate({ kind, source: currentSelection }) }
  async function download(format: 'docx' | 'pdf') {
    if (!snapshot || exporting) return
    const source = currentSelection
    const controller = new AbortController(); abort.current = controller; setExporting(true); setNotice('')
    try {
      const blob = await api.document(id, snapshot.revision, format, controller.signal)
      if (!live.current || controller.signal.aborted || selection.current !== source) return
      const url = URL.createObjectURL(blob); const link = document.createElement('a')
      link.href = url; link.download = `专题-${id}-v${snapshot.revision}.${format}`; link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      setNotice('已导出当前选定版本，未重新分析。')
    } catch {
      if (!controller.signal.aborted && selection.current === source) setNotice('导出未完成，请核对权限或文档服务后重试。')
    } finally { if (abort.current === controller) { abort.current = null; setExporting(false) } }
  }
  if (!allowed) return <main className="page-scrollable topics"><h1>专题研判</h1><p role="status">当前账号无专题研判权限，案件和地图浏览不受影响。</p></main>
  const views = !view.error && view.data?.snapshot_id === snapshot?.id && view.data?.content_sha256 === snapshot?.content_sha256 ? view.data : undefined
  const evidenceData = !evidence.error && evidence.data?.snapshot_id === snapshot?.id && evidence.data?.content_sha256 === snapshot?.content_sha256 ? evidence.data : undefined
  const totalPages = snapshot ? Math.max(1, Math.ceil(Math.max(Number(snapshot.aggregate.total), Number(snapshot.aggregate.pattern_total)) / 20)) : 1
  return <main className="page-scrollable topics">
    <header className="page-title"><h1>专题研判</h1><span className="sub">保存条件，复用依据</span></header>
    <p className="topic-intro">从全部授权历史案件中观察共同条件与变化。专题只保存分析条件和成果引用，不生成正式串并案关系。</p>
    <div className="topic-actions"><button className="btn-primary" onClick={() => setShowForm(v => !v)}>{showForm ? '收起新专题' : '新建专题'}</button>
      <Link to="/assistant">从研判助手保存条件</Link></div>
    {showForm && <section className="topic-section"><TopicForm pending={create.isPending} onCreate={(title, filters) => create.mutate({ title, filters, source: currentSelection })} />
      {create.error && <p role="alert">{topicError(create.error)}</p>}</section>}
    <div className="topic-layout"><aside aria-label="已保存专题">
      <h2>我的专题</h2>
      {list.isPending && <p role="status">正在读取专题…</p>}
      {list.error ? <p role="alert">{topicError(list.error)}</p> : <ul className="topic-list">{list.data?.items.map(item => <li key={item.id}>
        <Link aria-current={item.id === id ? 'page' : undefined} to={`/topics?topic=${item.id}`}>{item.title}</Link>
        <small>{topicState[item.refresh_state] || '状态待确认'}</small></li>)}</ul>}
      {!list.error && list.data?.total === 0 && <p>还没有专题。保存一次条件后，后续可直接查看新增依据。</p>}
      <div className="topic-actions"><button className="btn-ghost" disabled={listPage === 1} onClick={() => setListPage(v => v - 1)}>上一页专题</button>
        <button className="btn-ghost" disabled={!list.data || listPage * 20 >= list.data.total || !!list.error} onClick={() => setListPage(v => v + 1)}>下一页专题</button>
        <button className="btn-ghost" disabled={list.isFetching} onClick={() => void list.refetch()}>重新读取</button></div>
    </aside><div className="topic-detail">
      {invalid && <p role="alert">专题编号或版本无效，请从列表重新打开。</p>}
      {!id && <p>选择一个专题查看统计、案组、地图与材料。</p>}
      {id && detail.isPending && !invalid && <p role="status">正在读取专题与当前权限…</p>}
      {detail.error && <p role="alert">{topicError(detail.error)} <button className="btn-ghost" onClick={() => void detail.refetch()}>重新读取</button></p>}
      {topic && <>
        <h2>{topic.title}</h2><p role="status">{topicState[topic.refresh_state] || '状态待确认'}</p>
        <details><summary>当前专题条件（同时满足）</summary><ul>{filterLines(topic.filters).map(line => <li key={line}>{line}</li>)}</ul>
          {!filterLines(topic.filters).length && <p>全部授权案件，不限制案发时间。</p>}</details>
        <div className="topic-actions"><button className="btn-ghost" disabled={action.isPending || topic.paused} onClick={() => run('refresh')}>检查资料变化</button>
          <button className="btn-ghost" disabled={action.isPending} onClick={() => run('pause')}>{topic.paused ? '恢复自动更新' : '暂停自动更新'}</button>
          <button className="btn-ghost" onClick={() => { setParams({ topic: id }); void detail.refetch(); void history.refetch() }}>查看最新成果</button></div>
        {action.error && action.variables?.source === currentSelection && <p role="alert">{topicError(action.error)}</p>}
        {notice && <p role="status">{notice}</p>}
        {!snapshot && <p>尚未形成可用成果。后台会处理已保存的请求；等待时间较长时请管理员检查专题 Worker，案件录入不受影响。</p>}
        {snapshot && <>
          <p>正在查看第 {snapshot.revision} 版 · {snapshot.created_at}。自动更新不会替换当前阅读版本。</p>
          <details><summary>历史成果</summary>{history.error ? <p role="alert">{topicError(history.error)}</p> :
            <ul>{history.data?.items.map(item => <li key={item.revision}><button className="btn-ghost"
              onClick={() => setParams({ topic: id, revision: String(item.revision) })}>第 {item.revision} 版 · {item.created_at}</button></li>)}</ul>}
            <div className="topic-actions"><button className="btn-ghost" disabled={historyPage === 1} onClick={() => setHistoryPage(v => v - 1)}>较新版本</button>
              <button className="btn-ghost" disabled={!!history.error || !history.data || historyPage * 20 >= history.data.total} onClick={() => setHistoryPage(v => v + 1)}>较早版本</button></div>
          </details>
          <nav className="topic-tabs" aria-label="专题成果视图">{Object.entries(tabs).map(([key, title]) => <button className="btn-ghost" key={key}
            aria-pressed={tab === key} onClick={() => setTab(key as keyof typeof tabs)}>{title}</button>)}</nav>
          {tab === 'overview' ? <>
            <ProfileAggregateContent data={snapshot.aggregate} />
            <h3>与上一成果的变化</h3><ul>{[['added_case_ids', '新增来源'], ['updated_case_ids', '资料更新'], ['entered_group', '新入案组'], ['left_group', '移出案组']].map(([key, name]) =>
              <li key={key}>{name}：{Array.isArray(snapshot.changes[key]) ? (snapshot.changes[key] as unknown[]).length : '未提供'} 起</li>)}</ul>
            {snapshot.changes.comparison_state === 'restricted' && <p>部分历史来源已受限，变化不能作为完整对比。</p>}
            <p>独立事件 {snapshot.events.independent_event_count} 条；已关联案件事件 {snapshot.events.case_linked_event_count} 条。事件只按辖区与时间统计，不与案件数相加。</p>
          </> : view.error ? <p role="alert">{topicError(view.error)}</p> : views ?
            <TopicLinkedViews key={`${snapshot.id}:${page}`} views={views} tab={tab} /> : <p role="status">正在读取同版依据…</p>}
          <div className="topic-actions"><button className="btn-ghost" disabled={page <= 1} onClick={() => { setEvidenceId(null); setPage(v => v - 1) }}>上一页案例</button>
            <span>第 {page} / {totalPages} 页，计数不随分页变化</span><button className="btn-ghost" disabled={page >= totalPages} onClick={() => { setEvidenceId(null); setPage(v => v + 1) }}>下一页案例</button></div>
          <details><summary>核对本页案例的原文依据</summary><div className="topic-actions">{rowsOf(snapshot.aggregate.items).map(item =>
            <button className="btn-ghost" key={String(item.case_id)} onClick={() => setEvidenceId(Number(item.case_id))}>案件 #{String(item.case_id)}</button>)}</div>
            {evidenceId && evidence.isPending && <p role="status">正在核验原文版本…</p>}
            {evidence.error && <p role="alert">{topicError(evidence.error)}</p>}
            {evidenceData && <><p>{evidenceData.boundary}</p><ul>{evidenceData.assertions.map(item => <li key={item.evidence_ref}>
              {categoryNames[item.category]} · {kindNames[item.kind]}：{item.value}<blockquote>{item.reference.quote}</blockquote>
              <small>{item.evidence_ref}</small></li>)}</ul>
              {evidenceData.model_extraction && <section aria-label="已有模型提取候选">
                <h4>已有模型提取候选（与规则统计分开）</h4><p>{evidenceData.model_extraction.boundary}</p>
                <p>状态：{({ ready: '引用可核对', partial: '部分提取', not_enabled: '未启用', unavailable: '不可用',
                  invalid: '引用校验失败', profile_unavailable: '画像不可用' } as Record<string, string>)[evidenceData.model_extraction.state] || '未知'}</p>
                <ul>{evidenceData.model_extraction.items.map(item => <li key={item.evidence_ref}>
                  {categoryNames[item.category] || '行为片段'} · 模型标注为{kindNames[item.kind]}<blockquote>{item.reference.quote}</blockquote>
                  <small>{item.evidence_ref}</small></li>)}</ul>
              </section>}{evidenceData.information_gaps?.map(gap => <p key={gap}>{gap}</p>)}</>}
          </details>
          <div className="topic-actions"><button className="btn-ghost" disabled={exporting} onClick={() => void download('docx')}>导出本版 Word</button>
            <button className="btn-ghost" disabled={exporting} onClick={() => void download('pdf')}>导出本版 PDF</button>{exporting && <span role="status">正在生成材料…</span>}</div>
          <form className="topic-form" onSubmit={e => { e.preventDefault(); if (question.trim()) run('question') }}>
            <label>带着专题条件继续追问<textarea value={question} maxLength={2000} rows={2} onChange={e => setQuestion(e.target.value)} /></label>
            <p>追问沿用条件查询当前授权数据，注明来源专题版本；不是修改这一版冻结成果。模型未启用时专题统计仍可用。</p>
            <button className="btn-primary" disabled={action.isPending || !question.trim()}>交给研判助手</button>
          </form>
        </>}
        <details><summary>人工备注（不改变分析依据）</summary><form className="topic-form" onSubmit={e => { e.preventDefault(); run('notes') }}>
          <label>备注<textarea rows={3} maxLength={4000} value={notes} onChange={e => setNotes(e.target.value)} /></label>
          <button className="btn-ghost" disabled={action.isPending || notes === topic.notes}>保存备注</button></form></details>
      </>}
    </div></div>
  </main>
}
