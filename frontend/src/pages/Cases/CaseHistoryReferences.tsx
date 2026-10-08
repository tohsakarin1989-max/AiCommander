import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { caseHistoryApi, type CaseHistoryResult, type HistoryProcessComparison, type ProcessTextReference } from '../../services/caseHistory'
import { businessContextPath } from '../../services/businessNavigation'

const kinds: Record<string, string> = { stated: '原文陈述', negated: '原文否定', uncertain: '不确定', inferred: '推断' }
function conditions(values: [string, string, string][]) {
  return values.map(([, value, kind]) => `${value}（${kinds[kind] || '待核'}）`).join('、')
}
const dimensions: Record<string, string> = { action: '动作', time: '时间', object: '对象', location: '地点', measurement: '计量' }
function ProcessQuote({ label, reference }: { label: string; reference: ProcessTextReference }) {
  return <div><strong>{label}</strong><blockquote>{reference.quote}</blockquote>
    <small>{reference.field} · 字符 {reference.start + 1} 至 {reference.end} · 修订 #{reference.source_revision_id}</small></div>
}
function ProcessComparison({ value }: { value: HistoryProcessComparison }) {
  const labels = { stated_match: '共同明确陈述（不是事实链）', negated_match: '共同否定（不是行为支持）',
    uncertain: '不确定或推断（不计支持）', counter: '反向表述（不计支持）' }
  return <details><summary>当前案与历史案逐环节对照</summary>
    <p>{value.reason}</p><p>当前案 #{value.current.case_id} · 修订 {value.current.source_revision_id ?? '未形成'}；
      历史案 #{value.historical.case_id} · 修订 {value.historical.source_revision_id ?? '未形成'}。</p>
    {!value.coverage.complete && <p role="status">环节对照不完整{value.coverage.omitted_pairs ? `，另有 ${value.coverage.omitted_pairs} 对未在本页展开` : ''}，不能当作完整链条。</p>}
    {Object.entries(labels).map(([kind, label]) => {
      const pairs = value.pairs.filter(pair => pair.relation === kind)
      return pairs.length > 0 && <section key={kind} aria-label={label}><h5>{label}</h5>{pairs.map((pair, index) =>
        <div key={`${pair.current.event_id}:${pair.historical.event_id}:${index}`}><h6>规范化动作：{pair.action}</h6>
          <ProcessQuote label={`当前案 · ${kinds[pair.current.action_kind]}`} reference={pair.current.reference} />
          <ProcessQuote label={`历史案 · ${kinds[pair.historical.action_kind]}`} reference={pair.historical.reference} />
          {!!pair.shared_conditions.length && <p>两片段共同记载：{conditions(pair.shared_conditions)}</p>}
          {!!pair.counter_conditions.length && <p>局部反向条件：{conditions(pair.counter_conditions)}；不能按条件支持处理。</p>}
          {!!pair.current_only_conditions.length && <p>仅当前片段记载：{conditions(pair.current_only_conditions)}</p>}
          {!!pair.historical_only_conditions.length && <p>仅历史片段记载：{conditions(pair.historical_only_conditions)}；不能移入本案。</p>}
          {(!!pair.current_missing_dimensions.length || !!pair.historical_missing_dimensions.length) && <p>本案片段未记载：{pair.current_missing_dimensions.map(key => dimensions[key] || key).join('、') || '未提示'}；
            历史片段未记载：{pair.historical_missing_dimensions.map(key => dimensions[key] || key).join('、') || '未提示'}。未记载不等于未发生。</p>}
        </div>)}</section>
    })}
    {(['current', 'historical'] as const).map(side => {
      const rows = side === 'current' ? value.unmatched_current : value.unmatched_historical
      return rows.length > 0 && <details key={side}><summary>{side === 'current' ? '当前案' : '历史案'}未对应片段（{rows.length}）</summary>
        {rows.map(row => <ProcessQuote key={row.event_id} label={row.actions.map(action => `${action.value}（${kinds[action.kind]}）`).join('、') || '动作未明确'} reference={row.reference} />)}</details>
    })}
    <details><summary>双侧画像版本</summary><p>当前：{value.current.profile_id ?? '未就绪'} · {value.current.source_hash ?? '无修订摘要'}</p>
      <p>历史：{value.historical.profile_id ?? '未就绪'} · {value.historical.source_hash ?? '无修订摘要'}</p></details>
    <small>{value.boundary}</small>
  </details>
}

export function CaseHistoryContent({ result, context, originPath = '/cases' }: { result: CaseHistoryResult; context?: URLSearchParams; originPath?: string }) {
  const indexed = result.retrieval_mode === 'fragment_index'
  return <>
    {indexed ? <p>授权范围内 {result.coverage.authorized_cases} 起案件，已建索引 {result.coverage.indexed_cases} 起；本轮召回 {result.coverage.recalled_fragments} 个片段，复核 {result.coverage.scanned_cases} 起候选案件。最多展示三项参考，不是全库统计。</p>
      : <p>当前授权与筛选范围内 {result.coverage.authorized_cases} 起候选案件，本次已检查 {result.coverage.scanned_cases} 起；最多展示三项参考。</p>}
    {indexed && !!result.coverage.missing_index_cases && <p role="status">{result.coverage.missing_index_cases} 起案件的片段索引尚未就绪，不能把未检索资料当作没有关联。</p>}
    {indexed && result.coverage.recall_truncated && <p>本轮达到片段召回上限，仅提供有限历史参考，不宣称全库穷尽。</p>}
    {indexed && !!result.coverage.process_missing_cases && <p>{result.coverage.process_missing_cases} 起案件尚无当前过程画像，已建原文索引仍可检索，不代表过程关系已完整。</p>}
    {result.semantic_index_state === 'not_enabled' && <p>当前使用结构条件与本地词项检索，语义向量索引未启用。</p>}
    {result.semantic_index_state === 'unavailable' && <p>本地语义模型暂不可用，当前保留结构条件与词项结果，不能据此排除其他语义关联。</p>}
    {result.semantic_index_state === 'partial' && <p>部分资料尚无当前版本向量，本次联合检索不完整。</p>}
    {result.mode === 'hybrid_local' && <p>已结合结构条件、词项与本地语义进行名次融合，相似程度不是准确概率。</p>}
    {!result.coverage.complete && <p role="status">本次检索未完成全部范围，以下是部分结果，不能据此判断没有其他相关资料。</p>}
    {!indexed && !!result.coverage.missing_derived_sources && <p>有 {result.coverage.missing_derived_sources} 项来源缺少当前画像或索引，仅作词项检索，未重新抽取案情。</p>}
    {result.items.length === 0 && result.coverage.complete && <p>本次条件未找到匹配的历史参考，不表示案件没有线索。</p>}
    <ul>{result.items.map(item => <li key={`${item.source_type}:${item.source_id}`}>
      <Link to={context ? businessContextPath(item.route, context, originPath) : item.route}>{item.title}</Link>
      <p>{item.snippet}</p>
      {item.fragment && <details><summary>命中片段与原文位置</summary>
        <blockquote>{item.fragment.reference.quote}</blockquote>
        <p>字段：{item.fragment.reference.field} · 字符 {item.fragment.reference.start + 1} 至 {item.fragment.reference.end} · 来源版本：{item.fragment.source_revision_id ?? '父来源版本见下方'}</p>
        <p>召回依据：{[item.structural_rank != null && '结构条件', item.lexical_rank != null && '词项', item.semantic_rank != null && '本地语义'].filter(Boolean).join('、') || '版本化片段'}。相似不等于事实关联。</p>
      </details>}
      <p>{item.source_type === 'case' ? '历史案件资料' : '已确认历史经验，当前适用性仍需核对'}</p>
      {(item.profile_state === 'lexical_only' || item.derived_state === 'missing') && <p>仅词项匹配，未形成可引用的结构条件。</p>}
      {(['stated', 'negated', 'uncertain', 'inferred'] as const).map(kind => {
        const shared = item.shared_conditions.filter(condition => condition[2] === kind)
        return shared.length > 0 && <p key={kind}>{kind === 'stated' ? '共同陈述条件' : kind === 'negated' ? '共同否定（不计行为支持）' : '共同不确定或推断（不计支持）'}：{conditions(shared)}</p>
      })}
      {!!item.different_conditions.length && <p>不同表述：{conditions(item.different_conditions)}</p>}
      {!!item.unmatched_query_conditions.length && <details><summary>本案条件在该资料中尚未匹配</summary>
        <p>{conditions(item.unmatched_query_conditions)}</p></details>}
      {item.process_comparison ? <ProcessComparison value={item.process_comparison} />
        : item.source_type === 'case' && <p>本份参考未包含双侧过程对照，仅按已列片段和条件核对，不补造环节。</p>}
      <details><summary>来源版本</summary><dl>{Object.entries(item.versions).map(([key, value]) =>
        <div key={key}><dt>{key}</dt><dd>{value ?? '未形成'}</dd></div>)}</dl></details>
    </li>)}</ul>
    <small>{result.boundary}</small>
  </>
}

export function CaseHistoryPreview({ result, context }: { result: CaseHistoryResult; context: URLSearchParams }) {
  return <>
    <p>只读查找已有历史资料，不另建分析任务；相似条件不等于正式案件关联。</p>
    {!result.coverage.complete && <p role="status">历史资料尚未全部检索，以下仅是有限参考。</p>}
    {result.semantic_index_state === 'unavailable' && <p>语义检索暂不可用，保留词项参考。</p>}
    {result.semantic_index_state === 'not_enabled' && <p>使用本地规则与词项，语义模型未启用。</p>}
    {!result.items.length && <p>{result.coverage.complete ? '当前条件未找到历史参考，不表示没有线索。' : '暂未取得参考，不能视为没有相关资料。'}</p>}
    <ul>{result.items.slice(0, 3).map(item => <li key={`${item.source_type}:${item.source_id}`}>
      <Link to={businessContextPath(item.route, context, '/cases')}>{item.title}</Link>
      <p>{item.shared_conditions.length ? conditions(item.shared_conditions) : '词项命中，结构条件尚待核对'}</p>
    </li>)}</ul>
    <Link to={businessContextPath(`/cases?caseId=${result.source_case_id}&case_view=relations`, context, '/cases')}>查看相似条件、差异与原文依据</Link>
  </>
}

export function historyReferenceUnavailable(context: URLSearchParams) {
  return ['valid_at', 'valid_from', 'valid_to', 'known_at', 'knowledge_mode'].some(key => context.has(key)) || context.get('time_scope') === 'frozen_result'
}

export default function CaseHistoryReferences({ caseId, revision, compact = false }: { caseId: number; revision?: string; compact?: boolean }) {
  const { user, sessionEpoch } = useAuth()
  const [context] = useSearchParams()
  const historical = historyReferenceUnavailable(context)
  const query = useQuery({ queryKey: ['case-history', caseId, user?.id, sessionEpoch, revision, historical],
    queryFn: ({ signal }) => caseHistoryApi.read(caseId, signal), enabled: !!user && !historical,
    retry: false, gcTime: 0, staleTime: 0, refetchOnWindowFocus: false })
  const result = !query.isError && query.data?.source_case_id === caseId ? query.data : undefined
  if (historical) return <section className="detail-section" aria-label="历史案件与经验参考"><h3>历史案件与经验参考</h3>
    <p role="status">此历史时间条件下的案件参考未冻结，无法还原当时已知范围；未改查当前索引。设施的分时段条件与已有冻结材料仍可分别查看。</p></section>
  return <section className="detail-section" aria-label="历史案件与经验参考">
    <h3>历史案件与经验参考</h3>
    {query.isError ? <p role="alert">历史检索暂不可用，不影响案件录入，也不代表没有匹配资料。</p>
      : query.isPending ? <p role="status">正在查询授权范围内的历史资料…</p>
        : result ? compact ? <CaseHistoryPreview result={result} context={context} /> : <CaseHistoryContent result={result} context={context} /> : <p>历史参考来源尚未确认。</p>}
    <button className="btn-ghost" disabled={query.isFetching} onClick={() => void query.refetch()}>刷新历史参考</button>
  </section>
}
