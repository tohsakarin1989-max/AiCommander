import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { caseHistoryApi, type CaseHistoryResult } from '../../services/caseHistory'

const kinds: Record<string, string> = { stated: '原文陈述', negated: '原文否定', uncertain: '不确定', inferred: '推断' }
function conditions(values: [string, string, string][]) {
  return values.map(([, value, kind]) => `${value}（${kinds[kind] || '待核'}）`).join('、')
}

export function CaseHistoryContent({ result }: { result: CaseHistoryResult }) {
  return <>
    <p>当前授权与筛选范围内 {result.coverage.authorized_cases} 起候选案件，本次已检查 {result.coverage.scanned_cases} 起；最多展示三项参考。</p>
    {result.semantic_index_state === 'not_enabled' && <p>当前使用结构条件与本地词项检索，语义向量索引未启用。</p>}
    {result.semantic_index_state === 'unavailable' && <p>本地语义模型暂不可用，当前保留结构条件与词项结果，不能据此排除其他语义关联。</p>}
    {result.semantic_index_state === 'partial' && <p>部分资料尚无当前版本向量，本次联合检索不完整。</p>}
    {result.mode === 'hybrid_local' && <p>已结合结构条件、词项与本地语义进行名次融合，相似程度不是准确概率。</p>}
    {!result.coverage.complete && <p role="status">本次检索未完成全部范围，以下是部分结果，不能据此判断没有其他相关资料。</p>}
    {result.items.length === 0 && result.coverage.complete && <p>本次条件未找到匹配的历史参考，不表示案件没有线索。</p>}
    <ul>{result.items.map(item => <li key={`${item.source_type}:${item.source_id}`}>
      <Link to={item.route}>{item.title}</Link>
      <p>{item.snippet}</p>
      <p>{item.source_type === 'case' ? '历史案件资料' : '已确认历史经验，当前适用性仍需核对'}</p>
      {!!item.shared_conditions.length && <p>相似条件：{conditions(item.shared_conditions)}</p>}
      {!!item.different_conditions.length && <p>不同表述：{conditions(item.different_conditions)}</p>}
      {!!item.unmatched_query_conditions.length && <details><summary>本案条件在该资料中尚未匹配</summary>
        <p>{conditions(item.unmatched_query_conditions)}</p></details>}
      <details><summary>来源版本</summary><dl>{Object.entries(item.versions).map(([key, value]) =>
        <div key={key}><dt>{key}</dt><dd>{value ?? '未形成'}</dd></div>)}</dl></details>
    </li>)}</ul>
    <small>{result.boundary}</small>
  </>
}

export default function CaseHistoryReferences({ caseId, revision }: { caseId: number; revision?: string }) {
  const { user, sessionEpoch } = useAuth()
  const query = useQuery({ queryKey: ['case-history', caseId, user?.id, sessionEpoch, revision],
    queryFn: ({ signal }) => caseHistoryApi.read(caseId, signal), enabled: !!user,
    retry: false, gcTime: 0, staleTime: 0, refetchOnWindowFocus: false })
  const result = !query.isError && query.data?.source_case_id === caseId ? query.data : undefined
  return <section className="detail-section" aria-label="历史案件与经验参考">
    <h3>历史案件与经验参考</h3>
    {query.isError ? <p role="alert">历史检索暂不可用，不影响案件录入，也不代表没有匹配资料。</p>
      : query.isPending ? <p role="status">正在查询授权范围内的历史资料…</p>
        : result ? <CaseHistoryContent result={result} /> : <p>历史参考来源尚未确认。</p>}
    <button className="btn-ghost" disabled={query.isFetching} onClick={() => void query.refetch()}>刷新历史参考</button>
  </section>
}
