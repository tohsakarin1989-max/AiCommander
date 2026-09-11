import type { SituationBriefResult } from '../../services/intelligenceFlow'

const labels: Record<string, string> = {
  direction: '方向', gate: '门禁', access: '来源通行条件', max_height_m: '限高（米）', max_weight_t: '限重（吨）',
  valid_from: '有效起始', valid_until: '有效截止', open: '开放', closed: '关闭', unknown: '未知',
  permitted: '允许', prohibited: '禁止', forward: '正向', reverse: '反向', both: '双向',
  unreviewed: '未核验', verified: '已核验资料', rejected: '已驳回', pending_verification: '待重新核验',
  within_recorded_interval: '处于登记有效期', expired: '已到期', not_yet_effective: '尚未生效',
  validity_incomplete: '有效期不完整', invalid_validity: '有效期无效',
  geometry: '线形或点位', 'properties.conditions': '通行条件', 'properties.name': '名称',
  'properties.road_id': '关联道路', 'properties.kind': '要素类型', source_review: '资料核验', condition_validity: '条件有效期',
}
type Comparison = NonNullable<SituationBriefResult['comparison_snapshot']>

export default function RoadChanges({ data }: { data: NonNullable<Comparison['roads']> }) {
  const conditions = (values: Record<string, string | number> | null) => values === null ? '上期未登记'
    : Object.entries(values).map(([key, value]) => `${labels[key] || key}：${labels[String(value)] || value}`).join('；') || '未提供条件'
  const state = (value?: { validity: string; review_state: string } | null) => value
    ? `${labels[value.validity] || '待核'}；${labels[value.review_state] || '待核'}` : '无期末记录'
  return <details className="sw-semantic-changes">
    <summary>道路与入口资料变化（{data.items.length} 项）</summary>
    <p>{data.boundary}</p>
    {data.state !== 'compared' ? <p>资料不足或比较未完成，不代表道路没有变化。</p>
      : data.items.length === 0 ? <p>两个期末的已登记资料、核验状态和有效期状态未发现差异。</p>
        : <div className="sw-coverage-table"><table><caption>登记变化与版本证据，不是实际通行结论</caption>
          <thead><tr><th>道路或入口</th><th>变化</th><th>上期</th><th>本期</th><th>证据</th></tr></thead>
          <tbody>{data.items.map(item => <tr key={`${item.source_id}:${item.feature_id}`}>
            <th scope="row">{item.name}<br />{item.kind === 'entrance' ? '入口' : '道路'} · {item.feature_id}</th>
            <td>{item.change === 'newly_recorded' ? '新增登记' : item.changed_fields.map(field => labels[field] || '其他来源字段').join('、')}</td>
            <td>{conditions(item.previous_conditions)}<br />{state(item.previous_status)}</td>
            <td>{conditions(item.current_conditions)}<br />{state(item.current_status)}</td>
            <td>{item.evidence_refs.map(ref => <div key={ref}>{ref}</div>)}</td>
          </tr>)}</tbody>
        </table></div>}
    <p>{data.information_gaps.join('；')}</p>
  </details>
}
