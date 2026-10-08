import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { caseApi } from '../../services/cases'
import { formatCaseTime, formatOilVolume, formatStoredTime } from '../../utils/caseValues'
import type { CaseSourceRevisionDetail } from '../../types'
import { locationRoleLabels, measurementStageLabels } from './CaseSourceFields'
import { feedbackDescription } from './caseFeedback'

export function CaseSourceVersionCard({ source }: { source: CaseSourceRevisionDetail }) {
  const original = source.payload?.case
  if (!original) return <p role="alert">该版本的原文资料暂不可读，未用当前案件替代。</p>
  const precision = original.time_precision ?? (original.occurred_time ? 'exact' : 'unknown')
  const locations = source.payload.locations || []
  const measurements = source.payload.measurements || []
  return <article className="case-source-version" aria-label={`第 ${source.revision} 版原文记录`}>
    <h4>第 {source.revision} 版原文记录</h4>
    <p className="case-source-version-note">保存于 {formatStoredTime(source.created_at)}（北京时间）。以下内容来自该次保存，不是当前版本或系统推断。</p>
    <dl>
      <div><dt>发生时间</dt><dd>{formatCaseTime(original)} · {{ exact: '精确时刻', interval: '时间区间', unknown: '尚不明确' }[precision]}</dd></div>
      <div><dt>时间原文</dt><dd>{original.time_expression?.trim() || '未填写'}</dd></div>
      <div><dt>地点原文</dt><dd>{original.location?.trim() || '未填写，未据此猜测位置'}</dd></div>
      <div><dt>油品与数量</dt><dd>{original.oil_type || '油品未记录'} · {formatOilVolume(original.oil_volume, original.oil_volume_unit)}</dd></div>
      {original.discovered_at && <div><dt>发现时间</dt><dd>{formatStoredTime(original.discovered_at, 'YYYY-MM-DD HH:mm', original.time_timezone || 'Asia/Shanghai')}</dd></div>}
      {original.report_unit && <div><dt>报送单位</dt><dd>{original.report_unit}</dd></div>}
      <div><dt>本版已知公安反馈</dt><dd>{feedbackDescription(original, 'police_reported')}；{feedbackDescription(original, 'case_filed')}</dd></div>
      <div><dt>本版处置记录</dt><dd>人员：{original.person_handling || '未掌握'}；车辆：{original.vehicle_handling || '未掌握'}；油品：{original.oil_handling || '未掌握'}。移交不代表公安已办结。</dd></div>
    </dl>
    <h5>保存的案情原文</h5><p className="case-source-original">{original.description?.trim() || '该次保存未填写案情原文。'}</p>
    {!!locations.length && <><h5>该版本的地点记录</h5><ul>{locations.map((item, index) => <li key={index}>{locationRoleLabels[item.role]}：{item.description || '地点原文未填写'}（{{ exact: '精确位置', area: '仅知区域', unknown: '位置未明确' }[item.precision]}）</li>)}</ul></>}
    {!!measurements.length && <><h5>该版本的测量记录</h5><ul>{measurements.map((item, index) => <li key={index}>{measurementStageLabels[item.stage]}：{formatOilVolume(item.value, item.unit)} · {item.method || '测量方法未记录'}</li>)}</ul></>}
    <details><summary>技术详情（完整来源数据）</summary><pre>{JSON.stringify(source, null, 2)}</pre></details>
  </article>
}

export default function CaseSourceDetails({ caseId, revision }: { caseId: number; revision?: string | null }) {
  const { user, sessionEpoch } = useAuth()
  return <ScopedCaseSourceDetails key={`${caseId}:${user?.id}:${sessionEpoch}:${revision}`} caseId={caseId} revision={revision} />
}

function ScopedCaseSourceDetails({ caseId, revision }: { caseId: number; revision?: string | null }) {
  const { user, sessionEpoch } = useAuth()
  const [selected, setSelected] = useState<number | null>(null)
  const [pages, setPages] = useState<Array<number | undefined>>([undefined])
  const [referencePages, setReferencePages] = useState<Array<number | undefined>>([undefined])
  const key = [caseId, user?.id, sessionEpoch, revision]
  const sources = useQuery({ queryKey: ['case-sources', ...key, pages[pages.length - 1], referencePages[referencePages.length - 1]], queryFn: ({ signal }) => caseApi.getCaseSources(caseId, signal, { before_revision: pages[pages.length - 1], before_reference: referencePages[referencePages.length - 1], references_limit: 50 }), retry: false })
  const locations = useQuery({ queryKey: ['case-locations', ...key], queryFn: ({ signal }) => caseApi.getCaseLocations(caseId, signal), retry: false })
  const measures = useQuery({ queryKey: ['case-measurements', ...key], queryFn: ({ signal }) => caseApi.getCaseMeasurements(caseId, signal), retry: false })
  const detail = useQuery({ queryKey: ['case-source-revision', ...key, selected], queryFn: ({ signal }) => caseApi.getCaseSourceRevision(caseId, selected!, signal), enabled: Boolean(selected), retry: false })
  return <div className="detail-section case-source-details">
    <h3>来源修订</h3><p>原始提交与后续修改保留各自版本；下面的地点和数量是业务记录，不是系统推断。</p>
    {sources.isError ? <p role="alert">来源暂不可读，不能据此判断没有来源。<button className="btn-ghost-sm" onClick={() => void sources.refetch()}>重试本页</button><button className="btn-ghost-sm" disabled={pages.length === 1 && referencePages.length === 1} onClick={() => { setPages([undefined]); setReferencePages([undefined]); setSelected(null) }}>返回最近记录</button></p> : sources.isPending ? <p role="status">正在读取来源…</p> : <>
      <p>当前来源：{sources.data.current_revision_id ? `第 ${sources.data.current_revision ?? sources.data.revisions.find(item => item.id === sources.data.current_revision_id)?.revision ?? '待核对'} 版` : '尚未记录来源修订'}</p>
      <p>{sources.data.boundary}</p>
      <ul>{sources.data.revisions.map(item => <li key={item.id}><button className="btn-ghost-sm" onClick={() => setSelected(item.id)}>查看第 {item.revision} 版</button> · {formatStoredTime(item.created_at)}<details><summary>来源校验信息</summary><small>{item.source_hash}</small></details></li>)}</ul>
      <nav aria-label="来源版本分页"><button className="btn-ghost-sm" disabled={pages.length === 1 || sources.isFetching} onClick={() => { setPages(previous => previous.slice(0, -1)); setSelected(null) }}>较新版本</button><span>第 {pages.length} 页</span><button className="btn-ghost-sm" disabled={!sources.data.next_before_revision || sources.isFetching} onClick={() => { setPages(previous => [...previous, sources.data.next_before_revision!]); setSelected(null) }}>更早版本</button></nav>
      {!!sources.data.references.length && <details><summary>出处索引</summary><pre>{JSON.stringify(sources.data.references, null, 2)}</pre>
        <nav aria-label="出处索引分页"><button className="btn-ghost-sm" disabled={referencePages.length === 1 || sources.isFetching} onClick={() => setReferencePages(previous => previous.slice(0, -1))}>上一页</button><span>第 {referencePages.length} 页</span><button className="btn-ghost-sm" disabled={!sources.data.next_before_reference || sources.isFetching} onClick={() => setReferencePages(previous => [...previous, sources.data.next_before_reference!])}>下一页</button></nav>
      </details>}
    </>}
    {selected && !sources.isError && <section aria-label="来源版本原文">{detail.isError ? <p role="alert">该版本不可读取，未使用其他版本替代。</p> : detail.isPending ? <p>正在读取…</p> : detail.data ? <CaseSourceVersionCard source={detail.data} /> : <p role="alert">该版本资料暂不可读。</p>}</section>}
    <h3>地点角色</h3>{locations.isError ? <p role="alert">地点明细暂不可读。</p> : locations.isPending ? <p>正在读取…</p> : locations.data.length ? <ul>{locations.data.map((item, index) => <li key={item.id ?? index}>
      <strong>{locationRoleLabels[item.role]}</strong>：{item.description || '未填写地点原文'}<small>精度：{{ exact: '精确位置', area: '区域', unknown: '未知' }[item.precision]}；{item.geometry ? `已记录 ${item.geometry.type} 几何` : '未提供几何，不作为精确道路端点'}。{item.source_note}</small>
    </li>)}</ul> : <p>尚未补录独立地点角色，可保留未知。</p>}
    <h3>油品测量</h3><p>不同单位、测量方法和业务环节分别保留，不自动相加或换算。</p>
    {measures.isError ? <p role="alert">测量明细暂不可读。</p> : measures.isPending ? <p>正在读取…</p> : measures.data.length ? <ul>{measures.data.map((item, index) => <li key={item.id ?? index}>
      <strong>{measurementStageLabels[item.stage]}：{formatOilVolume(item.value, item.unit)}</strong><small>{item.method || '方法未记录'} · {formatStoredTime(item.measured_at)}{item.water_cut != null ? ` · 含水率 ${item.water_cut}%（${item.water_cut_basis || '口径未记录'}）` : ''} · {item.source_note || '来源说明未填写'}</small>
    </li>)}</ul> : <p>尚无测量记录，不等于数量为零。</p>}
  </div>
}
