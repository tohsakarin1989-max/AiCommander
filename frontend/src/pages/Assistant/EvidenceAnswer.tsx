import type { EvidenceAnswer as Answer, QueryCard } from '../../services/intelligentQueries'
import { lazy, Suspense, useState } from 'react'
const BusinessAnswerMap = lazy(() => import('./BusinessAnswerMap'))

export function answerValid(value: unknown, cards: QueryCard[]): value is Answer {
  if (!value || typeof value !== 'object') return false
  const answer = value as Answer
  const common = ['query-answer-6.4-1', 'business-answer-8.4-1'].includes(answer.schema_version) && typeof answer.summary === 'string'
    && typeof answer.boundary === 'string' && Array.isArray(answer.information_gaps)
    && answer.information_gaps.every(item => typeof item === 'string') && Array.isArray(answer.findings)
    && answer.findings.every(item => item && typeof item.text === 'string' && Number.isInteger(item.card_index)
      && item.card_index >= 0 && item.card_index < cards.length && Array.isArray(item.evidence_refs)
      && item.evidence_refs.every(ref => typeof ref === 'string'))
  if (!common || answer.schema_version === 'query-answer-6.4-1') return common
  return typeof answer.direct_answer === 'string'
    && ['answered', 'partial', 'insufficient_data', 'service_unavailable'].includes(answer.completeness || '')
    && [answer.evidence, answer.differences].every(items => Array.isArray(items) && items.every(item => item
      && typeof item.text === 'string' && Array.isArray(item.evidence_refs) && item.evidence_refs.every(ref => typeof ref === 'string')))
    && Array.isArray(answer.unanswered) && answer.unanswered.every(item => typeof item === 'string')
    && !!answer.time_scope_versions && typeof answer.time_scope_versions.algorithm_version === 'string'
    && typeof answer.time_scope_versions.scope_version === 'string' && typeof answer.time_scope_versions.answered_at === 'string'
    && !!answer.time_scope_versions.source_context && Array.isArray(answer.time_scope_versions.source_versions)
    && answer.time_scope_versions.source_versions.every(row => row && typeof row.kind === 'string'
      && ['string', 'number'].includes(typeof row.id) && (row.version === null || ['string', 'number'].includes(typeof row.version)))
}

export default function EvidenceAnswer({ answer, cards }: { answer: unknown; cards: QueryCard[] }) {
  const [showMap, setShowMap] = useState(false)
  if (!answerValid(answer, cards)) return <p role="alert">答案依据结构不完整，请核对下方工具结果，不能据此作出结论。</p>
  if (answer.schema_version === 'business-answer-8.4-1') return <section className="query-answer" aria-label="业务问题的完整回答">
    <h2>{{ answered: '已回答', partial: '部分回答', insufficient_data: '资料不足', service_unavailable: '依赖服务不可用' }[answer.completeness!]}</h2>
    <p>{answer.direct_answer}</p>
    <h3>支持依据</h3>
    {answer.evidence!.length ? <ol>{answer.evidence!.map((item, index) => <li key={index}><p>{item.text}</p>
      <small>来源：{item.evidence_refs.join('；') || '范围与版本见下方，不包含对象事实判断'}</small></li>)}</ol> : <p>尚无足够支持依据。</p>}
    <h3>差异或反向情况</h3>
    {answer.differences!.length ? <ul>{answer.differences!.map((item, index) => <li key={index}>
      <p>{item.text}</p><small>{item.evidence_refs.join('；')}</small>
    </li>)}</ul> : <p>未取得明确对照，不代表没有反向情况。</p>}
    {!!answer.unanswered!.length && <><h3>尚不能回答的部分</h3><ul>{answer.unanswered!.map((item, index) => <li key={index}>{item}</li>)}</ul></>}
    <details><summary>时间、范围与版本</summary>
      <p>回答形成：{answer.time_scope_versions!.answered_at}；规则：{answer.time_scope_versions!.algorithm_version}</p>
      {answer.time_scope_versions!.selection === 'all_authorized_history' && <p>历史检索范围：全部当前授权历史；下方区域仅表示源记录所属区域，不限制历史参考范围。</p>}
      {answer.time_scope_versions!.selection === 'explicit_area_history' && <p>历史检索范围：明确选择的区域 {answer.time_scope_versions!.history_area_filter}。</p>}
      <p>范围：{Object.entries(answer.time_scope_versions!.source_context).map(([key, value]) => `${({ case_id: '案件', asset_id: '设施', area_id: '区域',
        time_basis: '时间口径', period: '周期', as_of: '截止时间' } as Record<string, string>)[key] || key}：${({ discovery: '发现／查获', incident: '案发', entry: '录入', daily: '最近30个完整自然日', weekly: '相邻完整自然周' } as Record<string, string>)[String(value)] || String(value)}`).join('；')}</p>
      <ul>{answer.time_scope_versions!.source_versions.map((row, index) => <li key={index}>{row.kind} · {row.id} · 版本 {row.version ?? '未保存'}</li>)}</ul>
    </details>
    {answer.map_context && <details onToggle={event => setShowMap(event.currentTarget.open)}><summary>展开本回答的同源地图</summary>
      {showMap && <Suspense fallback={<p>正在加载冻结地图…</p>}><BusinessAnswerMap value={answer.map_context} /></Suspense>}
    </details>}
    <p className="query-history-note">{answer.boundary}</p>
  </section>
  return <section className="query-answer" aria-label="有依据的回答">
    <h2>回答与依据</h2><p>{answer.summary}</p>
    <ol>{answer.findings.map((finding, index) => <li key={index}>
      <p>{finding.text} <a href={`#query-card-${finding.card_index}`}>核对依据 {finding.card_index + 1}</a></p>
      {!!finding.evidence_refs.length && <details><summary>来源引用</summary><ul>{finding.evidence_refs.map((ref, i) => <li key={i}>{ref}</li>)}</ul></details>}
    </li>)}</ol>
    {!!answer.information_gaps.length && <><h3>尚不能回答的部分</h3><ul>{answer.information_gaps.map((gap, i) => <li key={i}>{gap}</li>)}</ul></>}
    <p className="query-history-note">{answer.boundary}</p>
  </section>
}
