import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { businessContextPath } from '../../services/businessNavigation'
import BusinessReturnLink from '../../components/BusinessReturnLink'
import { isMaterialTemplate, isMaterialTemplateApplicable, isResultKind, resultKinds, resultPath, resultsApi } from '../../services/results'
import type { ResultKind } from '../../services/results'
import MaterialReader from './MaterialReader'
import './Materials.css'

export default function Reports() {
  const { user, sessionEpoch } = useAuth()
  return <MaterialsWorkspace key={`${user?.id}:${sessionEpoch}`} identity={`${user?.id}:${sessionEpoch}`} allowed={user?.role === 'admin' || user?.role === 'analyst'} />
}
function MaterialsWorkspace({ identity, allowed }: { identity: string; allowed: boolean }) {
  const [params, setParams] = useSearchParams()
  const id = params.get('resultId') || ''
  const rawKind = params.get('kind') || (id ? 'case' : '')
  const invalid = !!id && (!isResultKind(rawKind) || !/^[A-Za-z0-9_-]{1,80}$/.test(id))
  const kind = isResultKind(rawKind) ? rawKind : undefined
  const rawTemplate = params.get('template') ?? 'full'
  const template = isMaterialTemplate(rawTemplate) ? rawTemplate : undefined
  const expectedContentSha256 = params.get('expected_content_sha256') ?? undefined
  const invalidTemplate = !!id && (params.getAll('template').length > 1 || !template || !!kind && !isMaterialTemplateApplicable(kind, template))
  const invalidVersion = !!id && (params.getAll('expected_content_sha256').length > 1
    || expectedContentSha256 !== undefined && !/^[a-f0-9]{64}$/.test(expectedContentSha256))
  const meetingId = params.get('meetingId') || undefined
  const inheritedCaseId = params.get('caseId') || undefined
  const subjectKind = meetingId ? 'meeting' : params.get('subject') || (inheritedCaseId ? 'case' : undefined)
  const subjectId = meetingId || params.get('subjectId') || inheritedCaseId
  const query = (params.get('catalogQ') || '').slice(0, 100)
  const filter = isResultKind(params.get('catalogKind')) ? params.get('catalogKind') as ResultKind : undefined
  const rawOffset = Number(params.get('catalogOffset'))
  const offset = Number.isSafeInteger(rawOffset) && rawOffset >= 0 ? Math.floor(rawOffset / 20) * 20 : 0
  const [draft, setDraft] = useState(query)
  useEffect(() => setDraft(query), [query])
  const updateCatalog = (values: Record<string, string | undefined>) => setParams(previous => {
    const next = new URLSearchParams(previous)
    Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key))
    return next
  })
  const list = useQuery({ queryKey: ['material-catalog', identity, query, filter, offset, subjectKind, subjectId],
    queryFn: ({ signal }) => resultsApi.list({ q: query, kind: filter, offset, limit: 20, subject_kind: subjectKind, subject_id: subjectId }, signal), retry: false, gcTime: 0 })
  const selected = useQuery({ queryKey: ['material-reader', identity, kind, id, template, expectedContentSha256],
    queryFn: ({ signal }) => resultsApi.read(kind!, id, signal, { template, expectedContentSha256 }),
    enabled: !!id && !invalid && !invalidTemplate && !invalidVersion, retry: false, gcTime: 0, refetchInterval: 30000 })
  const material = !invalid && !invalidTemplate && !invalidVersion && !selected.error && selected.data
    && selected.data.kind === kind && String(selected.data.id) === id && selected.data.presentation?.template === template
    && (!expectedContentSha256 || selected.data.content_sha256 === expectedContentSha256) ? selected.data : undefined
  return <main className="page-scrollable materials">
    <header className="page-title"><h1>成果与材料</h1><span className="sub">查阅已有内容，按需导出和判断</span></header>
    <BusinessReturnLink />
    <p>案件、设施、专题、态势和会议共用这一目录。查看不会启动新分析，也不要求每份材料经过审批。</p>
    {subjectKind && <p>当前限定来源：{subjectKind === 'meeting' ? '会议' : subjectKind === 'case' ? '案件' : subjectKind === 'facility' ? '设施' : '业务对象'} #{subjectId}。 <button className="btn-ghost" onClick={() => updateCatalog({ meetingId: undefined, subject: undefined, subjectId: undefined, caseId: undefined, catalogOffset: undefined })}>查看全部授权材料</button>
      {subjectKind === 'case' && /^[1-9]\d*$/.test(subjectId || '') && <Link className="btn-ghost" style={{ marginLeft: 8 }} to={businessContextPath(`/cases?caseId=${subjectId}`, params, '/reports')}>返回来源案件</Link>}
    </p>}
    <div className={`materials-layout ${id ? 'is-reading' : ''}`}><aside className="material-directory" aria-label="成果目录">
      <form onSubmit={event => { event.preventDefault(); updateCatalog({ catalogQ: draft.trim(), catalogOffset: undefined }) }}>
        <label>检索材料<input value={draft} maxLength={100} onChange={e => setDraft(e.target.value)} placeholder="标题、案件编号或内容关键词" /></label>
        <label>材料类型<select value={filter || ''} onChange={e => updateCatalog({ catalogKind: isResultKind(e.target.value) ? e.target.value : undefined, catalogOffset: undefined })}><option value="">全部类型</option>{Object.entries(resultKinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <button className="btn-ghost" disabled={list.isFetching}>查询</button></form>
      {list.error ? <p role="alert">目录暂不可读，未展示上次内容。<button className="btn-ghost" onClick={() => void list.refetch()}>重试</button></p>
        : list.isPending ? <p role="status">正在核对授权与材料…</p>
          : !list.data?.items.length ? <p>当前范围尚无可读材料。不代表没有业务资料，也不需要为填充目录重复生成。</p>
            : <ul>{list.data.items.map(item => <li key={`${item.kind}:${item.id}`}><Link aria-current={item.id === id && item.kind === kind ? 'page' : undefined} to={resultPath(item.kind, item.id, params)}>
              <small>{resultKinds[item.kind]} · {item.created_at}</small><strong>{item.title}</strong></Link></li>)}</ul>}
      <nav aria-label="材料目录分页"><button className="btn-ghost" disabled={offset === 0 || list.isFetching} onClick={() => updateCatalog({ catalogOffset: String(Math.max(0, offset - 20)) })}>上一页</button><span>第 {offset / 20 + 1} 页</span><button className="btn-ghost" disabled={!!list.error || !list.data?.has_more || list.isFetching} onClick={() => updateCatalog({ catalogOffset: String(offset + 20) })}>下一页</button></nav>
    </aside><div className="material-reading-pane">
      {invalid ? <p role="alert">材料类型或编号无效，请从目录重新打开。</p>
        : invalidTemplate ? <p role="alert">材料格式无效或不适用于此类材料，已隐藏旧正文与地图。<button className="btn-ghost" onClick={() => updateCatalog({ template: 'full' })}>查看完整资料</button></p>
          : invalidVersion ? <p role="alert">内容版本参数无效，请从目录重新打开材料。</p>
        : selected.error && id ? <p role="alert">材料不存在、当前不可访问、内容版本已变化或格式读取失败，已隐藏旧正文与地图。<button className="btn-ghost" onClick={() => void selected.refetch()}>重新读取</button></p>
          : id && selected.isPending ? <p role="status">正在核对材料与来源权限…</p>
            : material ? <MaterialReader key={`${identity}:${material.kind}:${material.id}:${material.content_sha256}:${template}`} identity={identity} material={material} allowed={allowed} context={params}
              onTemplateChange={next => updateCatalog({ template: next, expected_content_sha256: material.content_sha256 })} onSaved={() => void selected.refetch()} />
              : id ? <p role="alert">返回的材料格式或内容版本不匹配，已隐藏旧正文与地图。</p>
                : <p>选择一份已有材料，查看同版正文、来源、地图和人工判断。</p>}
    </div></div>
  </main>
}
