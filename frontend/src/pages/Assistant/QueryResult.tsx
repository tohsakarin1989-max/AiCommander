import { Link } from 'react-router-dom'
import type { QueryCard } from '../../services/intelligentQueries'
import { rowsOf, textValue, toolNames } from './queryPresentation'

function EvidenceList({ label, value }: { label: string; value: unknown }) {
  const lines = Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []
  return <div><dt>{label}</dt><dd>{lines.length ? lines.join('；') : '未提供'}</dd></div>
}

function InsightContent({ row }: { row: Record<string, unknown> }) {
  const unavailable = row.content_state === 'unavailable'
  return <div className="query-insight-content">
    {row.content_state == null ? <p>历史查询仅记录数量和版本，可重新查询读取已有成果。</p>
      : unavailable ? <p>成果输入版本不可读取或已缺失，正文暂不展示。</p>
        : <>
          {row.summary != null && <p>{textValue(row.summary)}</p>}
          {row.content_state === 'partial' && <p>仅展示可核验证据的部分候选，不能据此认定其他候选不存在。</p>}
          {rowsOf(row.hypotheses).slice(0, 3).map((item, index) => <article key={textValue(item.id ?? index)}>
            <h3>{textValue(item.title)}</h3>
            <p>{textValue(item.claim)}</p>
            <p>规则支持度：{textValue(item.rule_support)}（不是准确概率）</p>
            <dl>
              <EvidenceList label="支持证据" value={item.supporting_evidence} />
              <EvidenceList label="反向证据" value={item.counter_evidence} />
              <EvidenceList label="信息缺口" value={item.information_gaps} />
              <EvidenceList label="证据引用" value={item.evidence_refs} />
            </dl>
            <p>{textValue(item.boundary)}</p>
          </article>)}
          {rowsOf(row.hypotheses).length === 0 && <p>未返回可展示候选，不代表已经排除关联。</p>}
        </>}
    <dl><EvidenceList label="成果信息缺口" value={row.information_gaps} /></dl>
    <small>画像：{textValue(row.case_profile_id)} · 地图：{textValue(row.map_snapshot_id)} · 算法：{textValue(row.algorithm_version)}</small>
  </div>
}

export function QueryResult({ card }: { card: QueryCard }) {
  const data = card.data || {}
  const rows = rowsOf(data.items)
  const publicData = data.public_places as { items?: unknown; state?: string } | undefined
  return <section className="query-result" aria-label={toolNames[card.tool] || '查询结果'}>
    <h2>{toolNames[card.tool] || '查询结果'}</h2>
    {card.state === 'empty' && <p>当前授权范围和筛选条件下没有匹配数据。</p>}
    {card.tool === 'count_cases' && <p>匹配案件：<strong>{textValue(data.count)}</strong> 起</p>}
    {card.tool === 'compare_periods' && <dl className="query-comparison">
      <div><dt>本期</dt><dd>{textValue(data.current_count)} 起</dd></div>
      <div><dt>上一等长周期</dt><dd>{textValue(data.previous_count)} 起</dd></div>
      <div><dt>数量变化</dt><dd>{textValue(data.change)} 起</dd></div>
    </dl>}
    {'total' in data && <p>共 {textValue(data.total)} 条，本次展示 {rows.length} 条。</p>}
    {rows.length > 0 && <ul className="query-records">{rows.map((row, index) => <li key={textValue(row.id ?? row.run_id ?? index)}>
      {card.tool === 'find_cases' && typeof row.id === 'number'
        ? <Link to={`/cases?caseId=${row.id}`}>{textValue(row.case_number)}</Link>
        : <strong>{textValue(row.name ?? row.run_id ?? row.id)}</strong>}
      <span>{textValue(row.case_type ?? row.asset_type ?? row.status)}</span>
      {row.location != null && <span>{textValue(row.location)}</span>}
      {row.occurred_time != null && <time>{textValue(row.occurred_time)}</time>}
      {row.evidence_ref != null && <small>来源：{textValue(row.evidence_ref)}</small>}
      {card.tool === 'summarize_results' && <InsightContent row={row} />}
    </li>)}</ul>}
    {publicData && <div><h3>公共地名参考</h3>
      {publicData.state === 'unavailable' ? <p>地名索引不可用，不能据此认定地点不存在。</p>
        : <ul>{rowsOf(publicData.items).map((row, index) => <li key={index}>{textValue(row.name)}</li>)}</ul>}
    </div>}
    {card.information_gaps?.length ? <ul className="query-gaps">{card.information_gaps.map((gap, i) => <li key={i}>{gap}</li>)}</ul> : null}
    <details><summary>查询口径与来源</summary>
      <p>数据来源：{textValue(card.evidence?.source)}；查询时刻：{textValue(card.evidence?.queried_at)}</p>
      <dl>{Object.entries(card.evidence?.filters || {}).filter(([, value]) => value != null).map(([key, value]) =>
        <div key={key}><dt>{key}</dt><dd>{Array.isArray(value) ? value.map(textValue).join('、') : textValue(value)}</dd></div>)}</dl>
      <p>{card.boundary}</p>
    </details>
  </section>
}
