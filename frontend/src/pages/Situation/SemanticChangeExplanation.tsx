import type { SituationBriefResult } from '../../services/intelligenceFlow'

type Changes = NonNullable<NonNullable<SituationBriefResult['comparison_snapshot']>['semantic_changes']>
const kinds: Record<string, string> = { stated: '明确表述', negated: '否定表述', uncertain: '不确定表述', inferred: '推断表述' }

export default function SemanticChangeExplanation({ value }: { value: Changes }) {
  const changes = value.changes.filter(item => item.case_count_change !== 0)
  return <details className="sw-semantic-changes" open={value.state === 'comparable' && changes.length > 0}>
    <summary>手法、地点与时段表述变化</summary>
    <p>{value.boundary}</p>
    <p>可用画像：上期 {value.previous.readable_case_count}/{value.previous.case_count} 案，
      本期 {value.current.readable_case_count}/{value.current.case_count} 案。</p>
    {value.state !== 'comparable' ? <p>两期画像条件不同，暂不计算语义变化。</p>
      : changes.length === 0 ? <p>已比较的表述条件未见数量变化；不等于现实情况没有变化。</p>
        : <div className="sw-coverage-table"><table>
          <caption>涉及案件数量的变化，非词语次数或已确认事实</caption>
          <thead><tr><th>表述</th><th>性质</th><th>上期</th><th>本期</th><th>变化</th></tr></thead>
          <tbody>{changes.map(item => <tr key={`${item.category}:${item.value}:${item.kind}`}>
            <th>{item.value}</th><td>{kinds[item.kind] || '待核'}</td>
            <td>{item.previous_count}</td><td>{item.current_count}</td><td>{item.case_count_change}</td>
          </tr>)}</tbody>
        </table></div>}
    <p>{value.information_gaps.join('；')}</p>
  </details>
}
