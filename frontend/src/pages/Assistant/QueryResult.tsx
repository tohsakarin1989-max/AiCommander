import { Link } from 'react-router-dom'
import type { QueryCard } from '../../services/intelligentQueries'
import { rowsOf, textValue, toolNames } from './queryPresentation'
import { roadDetourLabel, type RoadDetourReference } from '../../services/roadAnalysis'
import { isCaseHistoryResult } from '../../services/caseHistory'
import { CaseHistoryContent } from '../Cases/CaseHistoryReferences'

const assertionKinds: Record<string, string> = { stated: '原文明述（未核实）', negated: '原文否定', uncertain: '不确定', inferred: '推断' }
function ProfileContent({ row }: { row: Record<string, unknown> }) {
  return <div className="query-insight-content">
    {typeof row.case_id === 'number' && <Link to={`/cases?caseId=${row.case_id}`}>查看案件 {textValue(row.case_number)}</Link>}
    <p>画像版本：{textValue(row.profile_version)}；规则：{textValue(row.rule_version)}；内容状态：{textValue(row.content_state)}</p>
    {rowsOf(row.assertions).map((item, index) => {
      const reference = item.reference as Record<string, unknown> | undefined
      return <article key={index}><strong>{textValue(item.value)} · {assertionKinds[String(item.kind)] || '未知'}</strong>
        <blockquote>{textValue(reference?.quote)}</blockquote>
        <small>出处：{textValue(reference?.field)}，字符 {textValue(reference?.start)}—{textValue(reference?.end)}；原文摘要 {textValue(reference?.source_sha256)}</small>
      </article>
    })}
    {Array.isArray(row.information_gaps) && row.information_gaps.length > 0 && <p>信息缺口：{row.information_gaps.map(gap =>
      typeof gap === 'string' ? gap : [gap?.field, gap?.code].filter(Boolean).join('：')).join('；')}</p>}
  </div>
}

function RoadContent({ row }: { row: Record<string, unknown> }) {
  const target = row.target as { name?: unknown } | undefined
  const distance = typeof row.distance_m === 'number' && Number.isFinite(row.distance_m)
    ? `${(row.distance_m / 1000).toFixed(2)} 公里` : '未提供'
  return <div className="query-insight-content">
    {typeof row.case_id === 'number' && <Link to={`/cases?caseId=${row.case_id}`}>查看案件 #{row.case_id}</Link>}
    {row.operation === 'route' ? <>
      <p>候选：{textValue(target?.name)}；沿路距离：{distance}；备选路径 {textValue(row.alternative_count)} 条。</p>
      <p>{roadDetourLabel(row.detour_reference as RoadDetourReference | undefined)}</p>
    </> : <p>留存距离比较：{rowsOf(row.cells).map(cell => typeof cell.distance_m === 'number'
      ? `${(cell.distance_m / 1000).toFixed(2)} 公里` : '未完成计算').join('；') || '暂无可展示距离'}。
      目标顺序对应留存成果，不将列表位置认定为实际来源。</p>}
    <p>{textValue(row.boundary)}</p>
    <small>计算时刻：{textValue(row.analysis_at)} · 地图：{textValue(row.map_snapshot_id)} · 通行条件版本：{textValue(row.policy_revision)}</small>
    <details><summary>道路版本与证据</summary><p>路网：{textValue(row.network_id)}；图摘要：{textValue(row.graph_sha256)}</p>
      <p>源成果：{textValue(row.result_id)}；留存摘要：{textValue(row.artifact_sha256)}</p></details>
  </div>
}

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
    {card.state === 'empty' && card.tool !== 'find_history' && <p>当前授权范围和筛选条件下没有匹配数据。</p>}
    {card.tool === 'find_history' && (isCaseHistoryResult(data)
      ? <CaseHistoryContent result={data} /> : <p role="alert">历史参考结构或来源不完整，不能据此判断没有匹配资料。</p>)}
    {card.tool === 'count_cases' && <p>匹配案件：<strong>{textValue(data.count)}</strong> 起</p>}
    {card.tool === 'compare_periods' && <dl className="query-comparison">
      <div><dt>本期</dt><dd>{textValue(data.current_count)} 起</dd></div>
      <div><dt>上一等长周期</dt><dd>{textValue(data.previous_count)} 起</dd></div>
      <div><dt>数量变化</dt><dd>{textValue(data.change)} 起</dd></div>
    </dl>}
    {'total' in data && <p>共 {textValue(data.total)} 条，本次展示 {rows.length} 条。</p>}
    {card.tool === 'find_road_results' && <p>本批读取 {rows.length} 份历史道路成果，不是案件总数。
      {data.next_page != null && `可继续查询第 ${textValue(data.next_page)} 批。`}</p>}
    {rows.length > 0 && card.tool !== 'find_history' && <ul className="query-records">{rows.map((row, index) => <li key={textValue(row.id ?? row.run_id ?? index)}>
      {card.tool === 'find_cases' && typeof row.id === 'number'
        ? <Link to={`/cases?caseId=${row.id}`}>{textValue(row.case_number)}</Link>
        : <strong>{card.tool === 'find_road_results' ? (row.operation === 'route' ? '留存参考路径' : '留存距离比较') : textValue(row.case_number ?? row.name ?? row.run_id ?? row.id)}</strong>}
      {!['find_road_results', 'find_case_profiles'].includes(card.tool) && <span>{textValue(row.case_type ?? row.asset_type ?? row.status)}</span>}
      {row.location != null && <span>{textValue(row.location)}</span>}
      {row.occurred_time != null && <time>{textValue(row.occurred_time)}</time>}
      {row.evidence_ref != null && <small>来源：{textValue(row.evidence_ref)}</small>}
      {card.tool === 'summarize_results' && <InsightContent row={row} />}
      {card.tool === 'find_road_results' && <RoadContent row={row} />}
      {card.tool === 'find_case_profiles' && <ProfileContent row={row} />}
    </li>)}</ul>}
    {card.tool === 'find_case_profiles' && <section><h3>本批表述分布（非全库统计）</h3>
      <ul>{rowsOf(data.batch_patterns).map((item, index) => <li key={index}>{textValue(item.value)} · {assertionKinds[String(item.kind)] || '未知'}：{textValue(item.case_count)} 起案件</li>)}</ul>
      <p>肯定、否定、不确定分别计算；同案相同表述不重复计数。{data.next_page != null ? `可继续读取第 ${textValue(data.next_page)} 批。` : ''}</p>
    </section>}
    {publicData && <div><h3>公共地名参考</h3>
      {publicData.state === 'unavailable' ? <p>地名索引不可用，不能据此认定地点不存在。</p>
        : <ul>{rowsOf(publicData.items).map((row, index) => <li key={index}>{textValue(row.name)}</li>)}</ul>}
    </div>}
    {card.tool !== 'find_history' && card.information_gaps?.length ? <ul className="query-gaps">{card.information_gaps.map((gap, i) => <li key={i}>{gap}</li>)}</ul> : null}
    <details><summary>查询口径与来源</summary>
      <p>数据来源：{textValue(card.evidence?.source)}；查询时刻：{textValue(card.evidence?.queried_at)}</p>
      <dl>{Object.entries(card.evidence?.filters || {}).filter(([, value]) => value != null).map(([key, value]) =>
        <div key={key}><dt>{key}</dt><dd>{Array.isArray(value) ? value.map(textValue).join('、') : textValue(value)}</dd></div>)}</dl>
      <p>{card.boundary}</p>
    </details>
  </section>
}
